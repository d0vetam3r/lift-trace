/* SPDX-License-Identifier: MIT
 * Optional local live bridge v1. All integers/doubles are little-endian.
 * Producer and consumer hold the named mutex while writing/copying this POD.
 * No pointer, platform bool, or compiler-dependent packing crosses the boundary.
 */
#ifndef LIFT_LIVE_PROTOCOL_H
#define LIFT_LIVE_PROTOCOL_H

#include <stddef.h>
#include "pacing-geometry.h"

#define LIFT_LIVE_VERSION 1u
#define LIFT_LIVE_EVENTS 4096u
#define LIFT_LIVE_SIZE 98472u
#define LIFT_LIVE_STALE_NS UINT64_C(1000000000)
#define LIFT_LIVE_FUTURE_NS UINT64_C(250000000)

struct lift_live_event {
	int32_t lane, direction;
	double start_ms, end_ms; /* -1 means the physical interval is still active. */
};

struct lift_live_packet {
	char magic[8];
	uint32_t version, size;
	uint64_t session, sequence, qpc_ns;
	double epoch_ms;
	uint32_t alive, count;
	/* green,sudden,lift,width,height,scratchWidth,blackRatio,noteHeight,
	 * speedScale,delay,shortThreshold,shortPercent,trailOpacity */
	double settings[13];
	uint32_t flags, reserved;
	struct lift_live_event events[LIFT_LIVE_EVENTS];
};

_Static_assert(sizeof(struct lift_live_event) == 24, "live event ABI");
_Static_assert(offsetof(struct lift_live_packet, qpc_ns) == 32, "QPC ABI");
_Static_assert(offsetof(struct lift_live_packet, epoch_ms) == 40, "epoch ABI");
_Static_assert(offsetof(struct lift_live_packet, settings) == 56, "settings ABI");
_Static_assert(offsetof(struct lift_live_packet, flags) == 160, "flags ABI");
_Static_assert(offsetof(struct lift_live_packet, events) == 168, "header ABI");
_Static_assert(sizeof(struct lift_live_packet) == LIFT_LIVE_SIZE, "packet ABI");

static inline bool lift_live_number(double value, double low, double high)
{
	return value >= low && value <= high; /* Also rejects NaN and infinity. */
}

static inline bool lift_live_integer(double value, uint32_t low, uint32_t high)
{
	return lift_live_number(value, low, high) && value == (double)(uint32_t)value;
}

static inline bool lift_live_valid(const struct lift_live_packet *packet)
{
	const char magic[8] = {'L','I','F','T','N','V','0','1'};
	for (unsigned i = 0; i < 8; ++i) if (packet->magic[i] != magic[i]) return false;
	if (packet->version != LIFT_LIVE_VERSION || packet->size != LIFT_LIVE_SIZE ||
	    !packet->session || !packet->sequence || !packet->qpc_ns ||
	    packet->alive > 1 || packet->count > LIFT_LIVE_EVENTS ||
	    (packet->flags & ~63u) || packet->reserved ||
	    !lift_live_number(packet->epoch_ms, 0, 100000000000000.0)) return false;
	const double *s = packet->settings;
	if (!lift_live_number(s[0], 50, 2000) || !lift_live_integer(s[2], 0, 999) ||
	    !lift_live_integer(s[1], 0, 999) || s[1] + s[2] > 999 ||
	    !lift_live_integer(s[3], 160, 3840) || !lift_live_integer(s[4], 1, 2160) ||
	    !lift_live_number(s[5], .5, 4) || !lift_live_number(s[6], .25, 2) ||
	    !lift_live_number(s[7], 2, 30) || !lift_live_number(s[8], .25, 4) ||
	    !lift_live_number(s[9], 0, 2000) || !lift_live_integer(s[10], 1, 2000) ||
	    !lift_live_integer(s[11], 1, 100) || !lift_live_number(s[12], 0, 1)) return false;
	unsigned active_lanes = 0;
	for (uint32_t i = 0; i < packet->count; ++i) {
		const struct lift_live_event *event = &packet->events[i];
		if (event->lane < 0 || event->lane > 7 || event->direction < -1 || event->direction > 1 ||
		    (event->lane != 0 && event->direction != 0) ||
		    !lift_live_number(event->start_ms, 0, 100000000000000.0) ||
		    !(event->end_ms == -1 || lift_live_number(event->end_ms, event->start_ms, 100000000000000.0)))
			return false;
		if (event->end_ms == -1) {
			unsigned bit = 1u << event->lane;
			if (active_lanes & bit) return false;
			active_lanes |= bit;
		}
	}
	return true;
}

static inline struct pacing_settings lift_live_settings(const struct lift_live_packet *packet)
{
	const double *s = packet->settings;
	return (struct pacing_settings){
		.green=s[0], .sudden=s[1], .lift=s[2], .width=s[3], .overlay_height=s[4],
		.scratch_width=s[5], .black_ratio=s[6], .note_height=s[7], .speed_scale=s[8],
		.delay_ms=s[9], .short_threshold_ms=s[10], .short_percent=s[11], .trail_opacity=s[12],
		.second_player=(packet->flags & 1) != 0, .auto_height=(packet->flags & 2) != 0,
		.body_enabled=(packet->flags & 4) != 0, .short_enabled=(packet->flags & 8) != 0,
		.guides=(packet->flags & 16) != 0, .transparent=(packet->flags & 32) != 0,
	};
}

/* Heartbeat uses the current OS clock, not the earlier OBS composition stamp.
 * A small negative frame-to-producer delta is normal and is handled below. */
static inline bool lift_live_fresh(const struct lift_live_packet *packet, uint64_t now_ns)
{
	if (!now_ns) return false;
	return now_ns >= packet->qpc_ns ? now_ns - packet->qpc_ns <= LIFT_LIVE_STALE_NS :
		packet->qpc_ns - now_ns <= LIFT_LIVE_FUTURE_NS;
}

static inline bool lift_live_animation(const struct lift_live_packet *packet,
				       uint64_t frame_ns, double *now_ms)
{
	if (!frame_ns) return false;
	double difference = frame_ns >= packet->qpc_ns ?
		(double)(frame_ns - packet->qpc_ns) / 1000000.0 :
		-(double)(packet->qpc_ns - frame_ns) / 1000000.0;
	if (difference < -5000 || difference > 5000) return false;
	*now_ms = packet->epoch_ms + difference;
	return lift_live_number(*now_ms, 0, 100000000000000.0);
}

/* Display-only transform of an unchanged keyboard or scratch interval. */
static inline bool lift_live_note(const struct pacing_settings *settings,
				 const struct lift_live_event *event, double now_ms,
				 struct pacing_note *note)
{
	double visual = now_ms - settings->delay_ms;
	if (event->start_ms > visual) return false;
	double speed = pacing_speed(settings) / 1000.0;
	if (event->end_ms != -1 && event->end_ms +
	    (settings->overlay_height + settings->note_height) / speed < visual) return false;
	bool active = event->end_ms == -1 || event->end_ms > visual;
	bool body = settings->body_enabled || event->lane == 0;
	double head = (visual - event->start_ms) * speed;
	double tail = active ? 0 : (visual - event->end_ms) * speed;
	if (body && event->lane != 0 && settings->short_enabled && settings->short_percent < 100 &&
	    !active && event->end_ms - event->start_ms < settings->short_threshold_ms)
		tail = head - (head - tail) * settings->short_percent / 100.0;
	*note = (struct pacing_note){event->lane, event->start_ms, event->end_ms, head, tail, active, body};
	return true;
}

#endif
