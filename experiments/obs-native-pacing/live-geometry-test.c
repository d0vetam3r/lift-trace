/* SPDX-License-Identifier: MIT
 * Stateless exports for cross-language protocol and real event geometry tests.
 * Build separately from the OBS plugin; no process, device or OBS is accessed.
 */
#include "live-protocol.h"
#ifdef _WIN32
#define TEST_EXPORT __declspec(dllexport)
#else
#define TEST_EXPORT
#endif

TEST_EXPORT int lift_test_packet_valid(const struct lift_live_packet *packet)
{
	return lift_live_valid(packet);
}

TEST_EXPORT int lift_test_packet_fresh(const struct lift_live_packet *packet, uint64_t now_ns)
{
	return lift_live_valid(packet) && lift_live_fresh(packet, now_ns);
}

TEST_EXPORT int lift_test_animation(const struct lift_live_packet *packet, uint64_t frame_ns, double *now_ms)
{
	return lift_live_valid(packet) && lift_live_animation(packet, frame_ns, now_ms);
}

/* out: x,width,head,tail,noteHeight,body,active,start,end,direction. */
TEST_EXPORT int lift_test_note(const struct lift_live_packet *packet, uint32_t index,
			      double now_ms, double *out)
{
	if (!lift_live_valid(packet) || index >= packet->count ||
	    !lift_live_number(now_ms, 0, 100000000000000.0)) return 0;
	struct pacing_settings settings = lift_live_settings(packet);
	struct pacing_note note;
	if (!lift_live_note(&settings, &packet->events[index], now_ms, &note)) return 0;
	struct pacing_lane lane = pacing_lane(&settings, note.lane);
	out[0] = lane.x + 3;
	out[1] = lane.width - 6 > 1 ? lane.width - 6 : 1;
	out[2] = note.head; out[3] = note.tail; out[4] = settings.note_height;
	out[5] = note.body_enabled; out[6] = note.active;
	out[7] = note.start_ms; out[8] = note.end_ms;
	out[9] = packet->events[index].direction;
	return 1;
}
