/* SPDX-License-Identifier: MIT
 * Experimental OBS-clock renderer. Optional live input uses a local shared
 * snapshot; the normal input engine, UI and history remain outside this module.
 */
#include <obs-module.h>
#include <util/platform.h>
#include <stdatomic.h>
#include "pacing-geometry.h"
#include "live-protocol.h"
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#endif

OBS_DECLARE_MODULE()

MODULE_EXPORT const char *obs_module_description(void)
{
	return "Lift Trace experimental native renderer with optional local live input";
}

struct pacing_snapshot {
	struct pacing_settings settings;
	double elapsed_ms, os_elapsed_ms;
	uint64_t tick;
	bool live, diagnostics, live_valid;
	double live_now_ms;
};

struct live_connection {
#ifdef _WIN32
	HANDLE mapping, mutex;
	const struct lift_live_packet *view;
#else
	bool unavailable;
#endif
};

struct pacing_source {
	atomic_flag lock;
	atomic_uint width, height;
	struct pacing_settings pending;
	struct pacing_snapshot frame;
	struct pacing_clock clock;
	uint64_t first_os_ns, previous_draw_us;
	struct live_connection connection;
	struct lift_live_packet *incoming, *cached;
	uint64_t blocked_session, blocked_sequence;
	bool live_requested, diagnostics, cache_valid;
	bool connection_changed;
#ifdef _WIN32
	HANDLE worker_thread, wake_event;
	char desired_channel[49];
	uint64_t channel_revision, attached_revision;
	bool worker_stop;
#endif
};

static void connection_close(struct live_connection connection)
{
#ifdef _WIN32
	if (connection.view) UnmapViewOfFile(connection.view);
	if (connection.mapping) CloseHandle(connection.mapping);
	if (connection.mutex) CloseHandle(connection.mutex);
#else
	(void)connection;
#endif
}

/* Only the connection worker calls this; never a video/update callback. */
static struct live_connection connection_open(const char *channel)
{
	struct live_connection result = {0};
#ifdef _WIN32
	if (!channel || !channel[0]) return result;
	size_t length = 0;
	for (; channel[length]; ++length) {
		unsigned char c = (unsigned char)channel[length];
		if (length >= 48 || !((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
		    (c >= '0' && c <= '9') || c == '-' || c == '_')) return result;
	}
	wchar_t name[96];
	const wchar_t prefix[] = L"Local\\LiftTraceNative-";
	size_t position = 0;
	while (prefix[position]) { name[position] = prefix[position]; ++position; }
	for (size_t i = 0; i < length; ++i) name[position++] = (wchar_t)channel[i];
	name[position] = 0;
	result.mapping = OpenFileMappingW(FILE_MAP_READ, FALSE, name);
	if (!result.mapping) return result;
	result.view = MapViewOfFile(result.mapping, FILE_MAP_READ, 0, 0, LIFT_LIVE_SIZE);
	const wchar_t suffix[] = L"-mutex";
	for (size_t i = 0; i < sizeof(suffix) / sizeof(*suffix); ++i) name[position + i] = suffix[i];
	result.mutex = OpenMutexW(SYNCHRONIZE | MUTEX_MODIFY_STATE, FALSE, name);
	if (!result.view || !result.mutex) {
		connection_close(result);
		result = (struct live_connection){0};
	}
#else
	(void)channel;
#endif
	return result;
}

static void lock_source(struct pacing_source *source)
{
	while (atomic_flag_test_and_set_explicit(&source->lock, memory_order_acquire)) {}
}

static void unlock_source(struct pacing_source *source)
{
	atomic_flag_clear_explicit(&source->lock, memory_order_release);
}

#ifdef _WIN32
static DWORD WINAPI connection_worker(LPVOID opaque)
{
	struct pacing_source *source = opaque;
	uint64_t previous_revision = UINT64_MAX;
	bool connected = false;
	for (;;) {
		char channel[49];
		lock_source(source);
		if (source->worker_stop) { unlock_source(source); break; }
		uint64_t revision = source->channel_revision;
		for (unsigned i = 0; i < 49; ++i) channel[i] = source->desired_channel[i];
		unlock_source(source);
		if (revision != previous_revision || (!connected && channel[0])) {
			struct live_connection connection = connection_open(channel);
			lock_source(source);
			if (source->worker_stop || revision != source->channel_revision) {
				unlock_source(source);
				connection_close(connection);
				continue;
			}
			struct live_connection previous = source->connection;
			source->connection = connection;
			source->connection_changed = true;
			source->attached_revision = revision;
			unlock_source(source);
			connection_close(previous);
			previous_revision = revision;
			connected = connection.view != NULL;
		}
		/* No polling once attached. An absent publisher is retried off the video
		 * thread; settings/stop signals wake this auto-reset event immediately. */
		WaitForSingleObject(source->wake_event, connected || !channel[0] ? INFINITE : 100);
	}
	return 0;
}

static void copy_channel(const char *input, char output[49])
{
	for (unsigned i = 0; i < 49; ++i) output[i] = 0;
	if (!input) return;
	unsigned length = 0;
	while (input[length]) {
		unsigned char c = (unsigned char)input[length];
		if (length >= 48 || !((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
		    (c >= '0' && c <= '9') || c == '-' || c == '_')) {
			output[0] = 0;
			return;
		}
		output[length++] = (char)c;
	}
}
#endif

static bool same_string(const char *left, const char *right)
{
	if (!left || !right) return false;
	while (*left && *left == *right) { ++left; ++right; }
	return *left == *right;
}

static double number_setting(obs_data_t *data, const char *name, double fallback,
			     double low, double high)
{
	if (!obs_data_has_user_value(data, name)) return fallback;
	double value = obs_data_get_double(data, name);
	/* NaN and infinity are not accepted as settings. */
	if (!(value >= -1.7976931348623157e308 && value <= 1.7976931348623157e308))
		return fallback;
	if (value < low) return low;
	if (value > high) return high;
	return value;
}

static bool bool_setting(obs_data_t *data, const char *name, bool fallback)
{
	return obs_data_has_user_value(data, name) ? obs_data_get_bool(data, name) : fallback;
}

static void source_update(void *opaque, obs_data_t *data)
{
	struct pacing_source *source = opaque;
	struct pacing_settings settings = pacing_defaults();
	/* The existing UI remains the settings owner. The lab passes a normalized
	 * snapshot under lift_settings. There is no second user settings file. */
	obs_data_t *lift = obs_data_get_obj(data, "lift_settings");
	if (lift) {
		settings.green = number_setting(lift, "greenNumber", settings.green, 50, 2000);
		settings.lift = number_setting(lift, "liftNumber", settings.lift, 0, 999);
		settings.sudden = number_setting(lift, "suddenNumber", settings.sudden, 0, 999 - settings.lift);
		settings.width = number_setting(lift, "width", settings.width, 160, 3840);
		settings.overlay_height = number_setting(lift, "overlayHeight", settings.overlay_height, 1, 2160);
		settings.scratch_width = number_setting(lift, "scratchWidth", settings.scratch_width, .5, 4);
		settings.black_ratio = number_setting(lift, "blackKeyRatio", settings.black_ratio, .25, 2);
		settings.note_height = number_setting(lift, "noteHeight", settings.note_height, 2, 30);
		settings.speed_scale = number_setting(lift, "speedScale", settings.speed_scale, .25, 4);
		settings.delay_ms = number_setting(lift, "delayMs", settings.delay_ms, 0, 2000);
		settings.short_threshold_ms = number_setting(lift, "shortInputThresholdMs", settings.short_threshold_ms, 1, 2000);
		settings.short_percent = number_setting(lift, "shortInputPercent", settings.short_percent, 1, 100);
		settings.trail_opacity = number_setting(lift, "trailOpacity", settings.trail_opacity, 0, 1);
		settings.body_enabled = bool_setting(lift, "inputBodyEnabled", settings.body_enabled);
		settings.short_enabled = bool_setting(lift, "shortInputEnabled", settings.short_enabled);
		settings.guides = bool_setting(lift, "showGuides", settings.guides);
		if (obs_data_has_user_value(lift, "heightMode"))
			settings.auto_height = !same_string(obs_data_get_string(lift, "heightMode"), "manual");
		if (obs_data_has_user_value(lift, "side"))
			settings.second_player = same_string(obs_data_get_string(lift, "side"), "2P");
		if (obs_data_has_user_value(lift, "background"))
			settings.transparent = same_string(obs_data_get_string(lift, "background"), "transparent");
		obs_data_release(lift);
	}
	const char *channel = obs_data_get_string(data, "live_channel");
	bool live_requested = channel && channel[0];
	obs_data_set_default_bool(data, "diagnostics", !live_requested);
	bool diagnostics = bool_setting(data, "diagnostics", !live_requested);
#ifdef _WIN32
	char desired[49];
	copy_channel(channel, desired);
#endif
	lock_source(source);
#ifdef _WIN32
	if (!same_string(source->desired_channel, desired)) {
		for (unsigned i = 0; i < 49; ++i) source->desired_channel[i] = desired[i];
		++source->channel_revision;
	}
#endif
	source->live_requested = live_requested;
	source->diagnostics = diagnostics;
	source->pending = settings;
	unlock_source(source);
#ifdef _WIN32
	if (source->wake_event) SetEvent(source->wake_event);
#endif
}

static const char *source_name(void *unused)
{
	(void)unused;
	return "Lift Trace native pacing experiment";
}

static void *source_create(obs_data_t *settings, obs_source_t *unused)
{
	(void)unused;
	struct pacing_source *source = bzalloc(sizeof(*source));
	if (!source) return NULL;
	source->incoming = bzalloc(sizeof(*source->incoming));
	source->cached = bzalloc(sizeof(*source->cached));
	if (!source->incoming || !source->cached) {
		bfree(source->incoming); bfree(source->cached); bfree(source);
		return NULL;
	}
	atomic_flag_clear(&source->lock);
	source_update(source, settings);
	source->frame.settings = source->pending;
	source->frame.live = source->live_requested;
	source->frame.diagnostics = source->diagnostics;
	atomic_init(&source->width, (unsigned)source->frame.settings.width);
	atomic_init(&source->height, (unsigned)source->frame.settings.overlay_height +
		(source->frame.diagnostics ? 100u : 0u));
#ifdef _WIN32
	source->wake_event = CreateEventW(NULL, FALSE, FALSE, NULL);
	if (source->wake_event)
		source->worker_thread = CreateThread(NULL, 0, connection_worker, source, 0, NULL);
	if (!source->worker_thread) {
		if (source->wake_event) CloseHandle(source->wake_event);
		bfree(source->incoming); bfree(source->cached); bfree(source);
		return NULL;
	}
#endif
	return source;
}

static void source_destroy(void *opaque)
{
	struct pacing_source *source = opaque;
#ifdef _WIN32
	lock_source(source);
	source->worker_stop = true;
	unlock_source(source);
	SetEvent(source->wake_event);
	WaitForSingleObject(source->worker_thread, INFINITE);
	CloseHandle(source->worker_thread);
	CloseHandle(source->wake_event);
#endif
	connection_close(source->connection);
	bfree(source->incoming);
	bfree(source->cached);
	bfree(source);
}

/* This function runs on the OBS video thread with the source lock held.
 * Shared state is copied only while owning its mutex with zero wait. Timeout
 * retains the last good snapshot until its original heartbeat expires. */
static void live_copy(struct pacing_source *source)
{
#ifdef _WIN32
	struct live_connection *connection = &source->connection;
	if (!connection->view || !connection->mutex) { source->cache_valid = false; return; }
	DWORD result = WaitForSingleObject(connection->mutex, 0);
	if (result == WAIT_TIMEOUT) return;
	if (result == WAIT_ABANDONED) {
		/* A dead writer may have stopped halfway through a copy. Do not accept
		 * this sequence again until a publisher completes a different packet. */
		source->blocked_session = connection->view->session;
		source->blocked_sequence = connection->view->sequence;
		source->cache_valid = false;
		ReleaseMutex(connection->mutex);
		return;
	}
	if (result != WAIT_OBJECT_0) { source->cache_valid = false; return; }
	*source->incoming = *connection->view;
	if (!ReleaseMutex(connection->mutex)) { source->cache_valid = false; return; }
	const struct lift_live_packet *packet = source->incoming;
	if (!lift_live_valid(packet) ||
	    (packet->session == source->blocked_session && packet->sequence == source->blocked_sequence) ||
	    (packet->session == source->cached->session && packet->sequence < source->cached->sequence)) {
		source->cache_valid = false;
		return;
	}
	*source->cached = *packet;
	source->cache_valid = true;
#else
	source->cache_valid = false;
#endif
}

static void source_tick(void *opaque, float seconds)
{
	(void)seconds;
	struct pacing_source *source = opaque;
	uint64_t frame_ns = obs_get_video_frame_time();
	uint64_t os_ns = os_gettime_ns();
	/* Never wait for an update on the video thread. A contended tick retains the
	 * previous frame; updates only hold this lock for a small handle/config swap. */
	if (atomic_flag_test_and_set_explicit(&source->lock, memory_order_acquire)) return;
	pacing_clock_advance(&source->clock, frame_ns);
	if (!source->first_os_ns) source->first_os_ns = os_ns;
	source->frame.live = source->live_requested;
	source->frame.diagnostics = source->diagnostics;
	source->frame.live_valid = false;
	if (source->live_requested) {
		if (source->connection_changed) {
			source->cache_valid = false;
			source->blocked_session = source->blocked_sequence = 0;
			source->connection_changed = false;
		}
#ifdef _WIN32
		if (source->attached_revision != source->channel_revision) source->cache_valid = false;
		else live_copy(source);
#else
		live_copy(source);
#endif
		if (source->cache_valid && lift_live_fresh(source->cached, os_ns)) {
			source->frame.settings = lift_live_settings(source->cached);
			source->frame.live_valid = source->cached->alive &&
				lift_live_animation(source->cached, frame_ns, &source->frame.live_now_ms);
		}
	} else {
		source->frame.settings = source->pending;
	}
	source->frame.elapsed_ms = source->clock.elapsed_ms;
	source->frame.os_elapsed_ms = os_ns >= source->first_os_ns ?
		(double)(os_ns - source->first_os_ns) / 1000000.0 : 0;
	if (source->clock.ready) ++source->frame.tick;
	atomic_store_explicit(&source->width, (unsigned)source->frame.settings.width, memory_order_relaxed);
	atomic_store_explicit(&source->height, (unsigned)source->frame.settings.overlay_height +
		(source->frame.diagnostics ? 100u : 0u), memory_order_relaxed);
	unlock_source(source);
}

static uint32_t source_width(void *opaque)
{
	struct pacing_source *source = opaque;
	return atomic_load_explicit(&source->width, memory_order_relaxed);
}

static uint32_t source_height(void *opaque)
{
	struct pacing_source *source = opaque;
	return atomic_load_explicit(&source->height, memory_order_relaxed);
}

struct painter { gs_effect_t *effect; gs_eparam_t *color; };

static void rectangle(struct painter *painter, double x, double y, double width,
		      double height, uint32_t rgb, double alpha)
{
	if (width <= 0 || height <= 0 || alpha <= 0) return;
	struct vec4 color;
	vec4_set(&color,
		(float)((rgb >> 16) & 255) / 255.0f,
		(float)((rgb >> 8) & 255) / 255.0f,
		(float)(rgb & 255) / 255.0f, (float)alpha);
	gs_effect_set_vec4(painter->color, &color);
	gs_matrix_push();
	gs_matrix_translate3f((float)x, (float)y, 0);
	gs_matrix_scale3f((float)width, (float)height, 1);
	while (gs_effect_loop(painter->effect, "Solid"))
		gs_draw_sprite(NULL, 0, 1, 1);
	gs_matrix_pop();
}

static void clipped_rectangle(struct painter *painter, const struct pacing_settings *settings,
			      double x, double y, double width, double height,
			      uint32_t rgb, double alpha)
{
	if (x < 0) { width += x; x = 0; }
	if (y < 0) { height += y; y = 0; }
	if (x + width > settings->width) width = settings->width - x;
	if (y + height > settings->overlay_height) height = settings->overlay_height - y;
	rectangle(painter, x, y, width, height, rgb, alpha);
}

struct point { double x, y; };

static bool point_inside(struct point point, int edge, double bound)
{
	return edge == 0 ? point.x >= bound : edge == 1 ? point.x <= bound :
		edge == 2 ? point.y >= bound : point.y <= bound;
}

/* Clip stroke quads before submitting triangles, just as Canvas clips the
 * circular scratch marker to the overlay. No per-frame graphics resource. */
static void stroke_quad(const struct pacing_settings *settings, struct point *quad)
{
	struct point first[12], second[12];
	for (unsigned i = 0; i < 4; ++i) first[i] = quad[i];
	unsigned count = 4;
	struct point *input = first, *output = second;
	for (int edge = 0; edge < 4 && count; ++edge) {
		double bound = edge == 1 ? settings->width : edge == 3 ? settings->overlay_height : 0;
		unsigned next_count = 0;
		struct point before = input[count - 1];
		bool before_inside = point_inside(before, edge, bound);
		for (unsigned i = 0; i < count; ++i) {
			struct point after = input[i];
			bool after_inside = point_inside(after, edge, bound);
			if (before_inside != after_inside) {
				double ratio = edge < 2 ? (bound - before.x) / (after.x - before.x) :
					(bound - before.y) / (after.y - before.y);
				output[next_count++] = (struct point){before.x + (after.x - before.x) * ratio,
					before.y + (after.y - before.y) * ratio};
			}
			if (after_inside) output[next_count++] = after;
			before = after; before_inside = after_inside;
		}
		count = next_count;
		struct point *temporary = input; input = output; output = temporary;
	}
	for (unsigned i = 1; i + 1 < count; ++i) {
		gs_vertex2f((float)input[0].x, (float)input[0].y);
		gs_vertex2f((float)input[i].x, (float)input[i].y);
		gs_vertex2f((float)input[i + 1].x, (float)input[i + 1].y);
	}
}

static void stroke_line(const struct pacing_settings *settings, struct point from,
			struct point to, double thickness)
{
	double dx = to.x - from.x, dy = to.y - from.y;
	double ax = dx < 0 ? -dx : dx, ay = dy < 0 ? -dy : dy;
	double length = ax + ay;
	if (length < .000001) return;
	/* Starting in [sqrt(n),sqrt(2n)], four Newton steps are ample here. */
	for (int i = 0; i < 4; ++i) length = .5 * (length + (dx * dx + dy * dy) / length);
	double x = -dy * thickness / (2 * length), y = dx * thickness / (2 * length);
	struct point quad[4] = {{from.x + x, from.y + y}, {to.x + x, to.y + y},
		{to.x - x, to.y - y}, {from.x - x, from.y - y}};
	stroke_quad(settings, quad);
}

static void scratch_arrow(struct painter *painter, const struct pacing_settings *settings,
			  double center_x, double center_y, double radius, int direction)
{
	if (radius <= 0 || center_y - radius * 2 > settings->overlay_height || center_y + radius * 2 < 0) return;
	for (int pass = 0; pass < 2; ++pass) {
		double thickness = pass == 0 ? (radius * .7 < 4 ? radius * .7 : 4) :
			(radius * .32 < 1.8 ? radius * .32 : 1.8);
		struct vec4 color;
		if (pass == 0) vec4_set(&color, 22.0f/255, 20.0f/255, 27.0f/255, 1);
		else vec4_set(&color, 1, 248.0f/255, 244.0f/255, 1);
		gs_effect_set_vec4(painter->color, &color);
		while (gs_effect_loop(painter->effect, "Solid")) {
			gs_render_start(true);
			/* Canvas path: clockwise 72..360 deg, counterclockwise 108..-180.
			 * 32 fixed segments use a rotation recurrence, with no libm calls. */
			double x = direction > 0 ? .30901699437494745 : -.30901699437494745;
			double y = .9510565162951535;
			for (int segment = 0; segment < 32; ++segment) {
				double next_x = x * .9876883405951378 - y * .15643446504023087 * direction;
				double next_y = y * .9876883405951378 + x * .15643446504023087 * direction;
				stroke_line(settings, (struct point){center_x + x * radius, center_y + y * radius},
					(struct point){center_x + next_x * radius, center_y + next_y * radius}, thickness);
				x = next_x; y = next_y;
			}
			double tip_x = center_x + radius * direction, wing = radius * .55;
			stroke_line(settings, (struct point){tip_x - wing, center_y - wing},
				(struct point){tip_x, center_y}, thickness);
			stroke_line(settings, (struct point){tip_x, center_y},
				(struct point){tip_x + wing, center_y - wing}, thickness);
			gs_render_stop(GS_TRIS);
		}
	}
}

static void draw_note(struct painter *painter, const struct pacing_settings *settings,
		      const struct pacing_note *note, int direction)
{
	struct pacing_lane lane = pacing_lane(settings, note->lane);
	double x = lane.x + 3, width = lane.width - 6;
	if (width < 1) width = 1;
	uint32_t color = note->lane == 0 ?
		(direction > 0 ? 0xffb4aa : direction < 0 ? 0xe45470 : 0xfc817e) :
		(note->lane % 2 == 0 ? 0x71b2ff : 0xe8edf5);
	if (note->body_enabled)
		clipped_rectangle(painter, settings, x, note->tail, width,
			note->head - note->tail, color, settings->trail_opacity);
	clipped_rectangle(painter, settings, x, note->head - settings->note_height / 2,
		width, settings->note_height, color, 1);
	if (note->body_enabled)
		clipped_rectangle(painter, settings, x, note->tail, width,
			settings->note_height < 2 ? settings->note_height : 2, color, .75);
	if (note->lane == 0 && direction) {
		double radius = (lane.width - 2) / 3.8;
		if (radius > 7) radius = 7;
		double displacement = (note->head - note->tail) / 2;
		if (displacement < 0) displacement = 0;
		if (displacement > 24) displacement = 24;
		scratch_arrow(painter, settings, x + width / 2, note->tail + displacement, radius, direction);
	}
}

static void overlay(struct painter *painter, const struct pacing_snapshot *frame,
		    const struct lift_live_packet *live)
{
	const struct pacing_settings *settings = &frame->settings;
	if (settings->auto_height && settings->lift == 0) return;
	if (!settings->transparent)
		rectangle(painter, 0, 0, settings->width, settings->overlay_height, 0, 1);
	if (settings->guides) {
		for (int lane = 0; lane < 8; ++lane) {
			struct pacing_lane geometry = pacing_lane(settings, lane);
			clipped_rectangle(painter, settings, geometry.x, 0, 1,
				settings->overlay_height, 0x899ab0, .22);
		}
	}
	if (frame->live) {
		if (!frame->live_valid) return;
		for (uint32_t i = 0; i < live->count; ++i) {
			struct pacing_note note;
			if (lift_live_note(settings, &live->events[i], frame->live_now_ms, &note))
				draw_note(painter, settings, &note, live->events[i].direction);
		}
		return;
	}
	int64_t first, last;
	pacing_note_range(settings, frame->elapsed_ms, &first, &last);
	for (int64_t index = first; index <= last; ++index) {
		struct pacing_note note;
		if (!pacing_note_at(settings, index, frame->elapsed_ms, &note)) continue;
		draw_note(painter, settings, &note, 0);
	}
}

static uint32_t barcode_number(double value)
{
	/* Timings are nonnegative. Convert after rounding, then wrap at 24 bits. */
	return (uint32_t)((uint64_t)(value + .5) & UINT64_C(0xffffff));
}

static void barcode(struct painter *painter, double top, uint32_t value)
{
	for (int bit = 0; bit < 24; ++bit)
		rectangle(painter, 8 + bit * 12, top, 10, 14,
			(value & (UINT32_C(1) << bit)) ? 0xffffff : 0, 1);
	rectangle(painter, 308, top, 12, 14, 0xffffff, 1);
	rectangle(painter, 324, top, 12, 14, 0, 1);
}

static void source_render(void *opaque, gs_effect_t *unused)
{
	(void)unused;
	struct pacing_source *source = opaque;
	/* tick and render share OBS's video thread; updates never write frame/cache. */
	struct pacing_snapshot frame = source->frame;
	uint64_t start_ns = os_gettime_ns();
	if (frame.live && !lift_live_fresh(source->cached, start_ns)) frame.live_valid = false;
	struct painter painter = {obs_get_base_effect(OBS_EFFECT_SOLID), NULL};
	if (!painter.effect) return;
	painter.color = gs_effect_get_param_by_name(painter.effect, "color");
	if (!painter.color) return;
	gs_blend_state_push();
	gs_blend_function_separate(GS_BLEND_SRCALPHA, GS_BLEND_INVSRCALPHA,
		GS_BLEND_ONE, GS_BLEND_INVSRCALPHA);
	overlay(&painter, &frame, source->cached);
	if (frame.diagnostics) {
		double top = frame.settings.overlay_height;
		rectangle(&painter, 0, top, frame.settings.width, 100, 0, 1);
		barcode(&painter, top + 10, (uint32_t)(frame.tick & UINT64_C(0xffffff)));
		barcode(&painter, top + 28, barcode_number(frame.elapsed_ms * 10));
		barcode(&painter, top + 46, barcode_number(frame.os_elapsed_ms * 10));
		barcode(&painter, top + 64, barcode_number((frame.live ? frame.live_now_ms : frame.elapsed_ms) * 10));
		barcode(&painter, top + 82, (uint32_t)(source->previous_draw_us & UINT64_C(0xffffff)));
	}
	gs_blend_state_pop();
	uint64_t end_ns = os_gettime_ns();
	source->previous_draw_us = end_ns >= start_ns ? (end_ns - start_ns) / 1000 : 0;
}

static obs_properties_t *source_properties(void *unused)
{
	(void)unused;
	obs_properties_t *properties = obs_properties_create();
	obs_properties_add_text(properties, "live_channel", "Live channel (empty: synthetic test)", OBS_TEXT_DEFAULT);
	obs_properties_add_bool(properties, "diagnostics", "Show diagnostic barcode");
	return properties;
}

static struct obs_source_info pacing_info = {
	.id = "lift_trace_native_pacing",
	.type = OBS_SOURCE_TYPE_INPUT,
	.output_flags = OBS_SOURCE_VIDEO | OBS_SOURCE_CUSTOM_DRAW,
	.get_name = source_name,
	.create = source_create,
	.destroy = source_destroy,
	.update = source_update,
	.get_width = source_width,
	.get_height = source_height,
	.video_tick = source_tick,
	.video_render = source_render,
	.get_properties = source_properties,
};

bool obs_module_load(void)
{
	obs_register_source(&pacing_info);
	return true;
}
