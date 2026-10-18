/* SPDX-License-Identifier: MIT
 * Shared native rendering geometry. No device access or input-history mutation.
 * Equations mirror web/engine.js and web/render.js; no event schedule is generated.
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
