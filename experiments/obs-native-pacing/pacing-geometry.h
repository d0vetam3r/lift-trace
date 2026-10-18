/* SPDX-License-Identifier: MIT
 * Synthetic benchmark geometry; live runtime has no generated note schedule.
 */
#ifndef LIFT_PACING_FIXTURE_H
#define LIFT_PACING_FIXTURE_H
#include "../../native/obs/pacing-geometry.h"

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

#endif
