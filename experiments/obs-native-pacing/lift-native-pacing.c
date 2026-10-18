/* SPDX-License-Identifier: MIT
 * Proof of concept only: OBS-clock keyboard geometry with synthetic inputs.
 * Does not open files, sockets, controllers, or any application service.
 */
#include <obs-module.h>
#include <util/platform.h>
#include <stdatomic.h>
#include "pacing-geometry.h"

OBS_DECLARE_MODULE()

MODULE_EXPORT const char *obs_module_description(void)
{
	return "Lift Trace synthetic native pacing experiment (not a gameplay renderer)";
}

struct pacing_snapshot {
	struct pacing_settings settings;
	double elapsed_ms, os_elapsed_ms;
	uint64_t tick;
};

struct pacing_source {
	atomic_flag lock;
	struct pacing_settings pending;
	struct pacing_snapshot frame;
	struct pacing_clock clock;
	uint64_t first_os_ns, previous_draw_us;
};

static void lock_source(struct pacing_source *source)
{
	while (atomic_flag_test_and_set_explicit(&source->lock, memory_order_acquire)) {}
}

static void unlock_source(struct pacing_source *source)
{
	atomic_flag_clear_explicit(&source->lock, memory_order_release);
}

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
	lock_source(source);
	source->pending = settings;
	unlock_source(source);
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
	atomic_flag_clear(&source->lock);
	source_update(source, settings);
	source->frame.settings = source->pending;
	return source;
}

static void source_destroy(void *opaque)
{
	/* No graphics resources, worker threads or external handles are owned. */
	bfree(opaque);
}

static void source_tick(void *opaque, float seconds)
{
	(void)seconds;
	struct pacing_source *source = opaque;
	uint64_t frame_ns = obs_get_video_frame_time();
	uint64_t os_ns = os_gettime_ns();
	/* tick/render run on OBS's video thread; update can run on another thread.
	 * The lock covers only POD copies and arithmetic, never graphics or I/O. */
	lock_source(source);
	pacing_clock_advance(&source->clock, frame_ns);
	if (!source->first_os_ns) source->first_os_ns = os_ns;
	source->frame.settings = source->pending;
	source->frame.elapsed_ms = source->clock.elapsed_ms;
	source->frame.os_elapsed_ms = os_ns >= source->first_os_ns ?
		(double)(os_ns - source->first_os_ns) / 1000000.0 : 0;
	if (source->clock.ready) ++source->frame.tick;
	unlock_source(source);
}

static uint32_t source_width(void *opaque)
{
	struct pacing_source *source = opaque;
	lock_source(source);
	uint32_t value = (uint32_t)source->frame.settings.width;
	unlock_source(source);
	return value;
}

static uint32_t source_height(void *opaque)
{
	struct pacing_source *source = opaque;
	lock_source(source);
	uint32_t value = (uint32_t)source->frame.settings.overlay_height + 100;
	unlock_source(source);
	return value;
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

static void overlay(struct painter *painter, const struct pacing_snapshot *frame)
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
	int64_t first, last;
	pacing_note_range(settings, frame->elapsed_ms, &first, &last);
	for (int64_t index = first; index <= last; ++index) {
		struct pacing_note note;
		if (!pacing_note_at(settings, index, frame->elapsed_ms, &note)) continue;
		struct pacing_lane lane = pacing_lane(settings, note.lane);
		double x = lane.x + 3, width = lane.width - 6;
		if (width < 1) width = 1;
		uint32_t color = (note.lane % 2 == 0) ? 0x71b2ff : 0xe8edf5;
		if (note.body_enabled)
			clipped_rectangle(painter, settings, x, note.tail, width,
				note.head - note.tail, color, settings->trail_opacity);
		clipped_rectangle(painter, settings, x, note.head - settings->note_height / 2,
			width, settings->note_height, color, 1);
		if (note.body_enabled)
			clipped_rectangle(painter, settings, x, note.tail, width,
				settings->note_height < 2 ? settings->note_height : 2, color, .75);
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
	struct pacing_snapshot frame;
	lock_source(source);
	frame = source->frame;
	unlock_source(source);
	uint64_t start_ns = os_gettime_ns();
	struct painter painter = {obs_get_base_effect(OBS_EFFECT_SOLID), NULL};
	if (!painter.effect) return;
	painter.color = gs_effect_get_param_by_name(painter.effect, "color");
	if (!painter.color) return;
	gs_blend_state_push();
	gs_blend_function_separate(GS_BLEND_SRCALPHA, GS_BLEND_INVSRCALPHA,
		GS_BLEND_ONE, GS_BLEND_INVSRCALPHA);
	overlay(&painter, &frame);
	double top = frame.settings.overlay_height;
	rectangle(&painter, 0, top, frame.settings.width, 100, 0, 1);
	barcode(&painter, top + 10, (uint32_t)(frame.tick & UINT64_C(0xffffff)));
	barcode(&painter, top + 28, barcode_number(frame.elapsed_ms * 10));
	barcode(&painter, top + 46, barcode_number(frame.os_elapsed_ms * 10));
	barcode(&painter, top + 64, barcode_number(frame.elapsed_ms * 10));
	barcode(&painter, top + 82, (uint32_t)(source->previous_draw_us & UINT64_C(0xffffff)));
	gs_blend_state_pop();
	uint64_t end_ns = os_gettime_ns();
	source->previous_draw_us = end_ns >= start_ns ? (end_ns - start_ns) / 1000 : 0;
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
};

bool obs_module_load(void)
{
	obs_register_source(&pacing_info);
	return true;
}
