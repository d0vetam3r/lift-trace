/* SPDX-License-Identifier: MIT
 * Isolated rendering experiment. No device access or input-history mutation.
 * Equations mirror web/engine.js and web/render.js; only synthetic keys exist.
 */
#ifndef LIFT_PACING_GEOMETRY_H
#define LIFT_PACING_GEOMETRY_H

#include <stdbool.h>
#include <stdint.h>

struct pacing_settings {
	double green, sudden, lift, width, overlay_height;
	double scratch_width, black_ratio, note_height, speed_scale, delay_ms;
	double short_threshold_ms, short_percent, trail_opacity;
	bool second_player, auto_height, body_enabled, short_enabled;
	bool guides, transparent;
};

struct pacing_lane { double x, width; };
struct pacing_note {
	int lane;
	double start_ms, end_ms, head, tail;
	bool active, body_enabled;
};

static inline struct pacing_settings pacing_defaults(void)
{
	return (struct pacing_settings){
		.green = 270, .sudden = 70, .lift = 401, .width = 432,
		.overlay_height = 290, .scratch_width = 5.0 / 3.0,
		.black_ratio = 7.0 / 9.0, .note_height = 12, .speed_scale = 1,
		.delay_ms = 0, .short_threshold_ms = 300, .short_percent = 50,
		.trail_opacity = .38, .second_player = false, .auto_height = true,
		.body_enabled = false, .short_enabled = true,
		.guides = true, .transparent = false,
	};
}

static inline double pacing_speed(const struct pacing_settings *s)
{
	return 723.0 * (1000.0 - s->sudden - s->lift) / 1000.0 *
	       600.0 / s->green * s->speed_scale;
}

static inline struct pacing_lane pacing_lane(const struct pacing_settings *s, int lane)
{
	double weights[8] = {s->scratch_width, 1, s->black_ratio, 1,
			    s->black_ratio, 1, s->black_ratio, 1};
	double unit = s->width / (s->scratch_width + 4 + 3 * s->black_ratio);
	double x = 0;
	for (int i = 0; i < 8; ++i) {
		int current = s->second_player ? (i + 1) % 8 : i;
		if (current == lane)
			return (struct pacing_lane){x, weights[current] * unit};
		x += weights[current] * unit;
	}
	return (struct pacing_lane){0, 0};
}

static inline int64_t pacing_floor(double value)
{
	int64_t truncated = (int64_t)value;
	return value < (double)truncated ? truncated - 1 : truncated;
}

/* Same continuous schedule as the browser fixture: 120 ms presses, 40 ms holds.
 * The earliest three presses predate the fixture epoch to populate the lane.
 * No event timestamps are rounded to an OBS frame or changed by appearance.
 */
static inline bool pacing_note_at(const struct pacing_settings *s, int64_t index,
				 double elapsed_ms, struct pacing_note *note)
{
	double visual_ms = elapsed_ms - s->delay_ms;
	double start = (double)index * 120.0, end = start + 40.0;
	if (index < -3 || start > visual_ms)
		return false;
	double speed = pacing_speed(s) / 1000.0;
	if (speed <= 0 || end + (s->overlay_height + s->note_height) / speed < visual_ms)
		return false;
	int lane = (int)((index % 7 + 7) % 7) + 1;
	bool active = end > visual_ms;
	double head = (visual_ms - start) * speed;
	double tail = active ? 0 : (visual_ms - end) * speed;
	if (s->body_enabled && s->short_enabled && s->short_percent < 100 &&
	    !active && 40.0 < s->short_threshold_ms)
		tail = head - (head - tail) * s->short_percent / 100.0;
	*note = (struct pacing_note){lane, start, end, head, tail, active, s->body_enabled};
	return true;
}

/* Match the bounded synthetic browser history (MAX_EVENTS = 4096). Scheduling
 * runs 250 ms ahead; very low configured speeds still cannot cause unbounded
 * work. The actual visible range normally has only a few notes.
 */
static inline void pacing_note_range(const struct pacing_settings *s, double elapsed_ms,
				    int64_t *first, int64_t *last)
{
	double speed = pacing_speed(s) / 1000.0;
	double visual = elapsed_ms - s->delay_ms;
	*last = pacing_floor(visual / 120.0);
	*first = speed > 0 ? pacing_floor((visual - 40.0 -
		(s->overlay_height + s->note_height) / speed) / 120.0) : *last + 1;
	int64_t oldest_retained = pacing_floor((elapsed_ms + 250.0) / 120.0) - 4095;
	if (*first < oldest_retained) *first = oldest_retained;
	if (*first < -3) *first = -3;
}

struct pacing_clock {
	uint64_t last_ns;
	double elapsed_ms;
	bool ready;
};

/* OBS supplies the animation clock. Zero/uninitialized time does not invent
 * elapsed time; a backwards clock rebases while preserving the visible age.
 * Forward gaps advance analytically, without queuing catch-up events.
 */
static inline void pacing_clock_advance(struct pacing_clock *clock, uint64_t frame_ns)
{
	if (!frame_ns) return;
	if (clock->ready && frame_ns >= clock->last_ns)
		clock->elapsed_ms += (double)(frame_ns - clock->last_ns) / 1000000.0;
	clock->last_ns = frame_ns;
	clock->ready = true;
}

#endif
