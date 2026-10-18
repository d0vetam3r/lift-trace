/* SPDX-License-Identifier: MIT
 * Standalone pure tests. A freestanding DLL can expose these to ctypes without
 * starting OBS or reading any user data. Zero return means success.
 */
#include "pacing-geometry.h"

#ifdef _WIN32
#define TEST_EXPORT __declspec(dllexport)
#else
#define TEST_EXPORT
#endif

static bool close_enough(double actual, double expected)
{
	double difference = actual - expected;
	return difference > -0.000001 && difference < 0.000001;
}

#define CHECK(condition) do { if (!(condition)) return __LINE__; } while (0)

TEST_EXPORT int pacing_geometry_tests(void)
{
	struct pacing_settings settings = pacing_defaults();
	CHECK(close_enough(pacing_speed(&settings), 849.9266666666666));
	struct pacing_lane scratch = pacing_lane(&settings, 0);
	CHECK(close_enough(scratch.x, 0));
	CHECK(close_enough(scratch.width, 90));
	CHECK(close_enough(pacing_lane(&settings, 1).x, 90));
	CHECK(close_enough(pacing_lane(&settings, 1).width, 54));
	CHECK(close_enough(pacing_lane(&settings, 2).width, 42));
	settings.second_player = true;
	CHECK(close_enough(pacing_lane(&settings, 1).x, 0));
	CHECK(close_enough(pacing_lane(&settings, 0).x, 342));
	settings.second_player = false;
	struct pacing_note note;
	CHECK(pacing_note_at(&settings, 0, 100, &note));
	CHECK(note.lane == 1 && !note.active && !note.body_enabled);
	CHECK(close_enough(note.head, 84.99266666666666));
	CHECK(close_enough(note.tail, 50.9956));
	CHECK(note.start_ms == 0 && note.end_ms == 40);
	CHECK(pacing_note_at(&settings, -1, 0, &note) && note.lane == 7);
	CHECK(!pacing_note_at(&settings, -4, 0, &note));
	CHECK(!pacing_note_at(&settings, 1, 100, &note));
	settings.body_enabled = true;
	settings.short_percent = 30;
	CHECK(pacing_note_at(&settings, 0, 100, &note));
	CHECK(close_enough(note.tail, 74.79354666666666));
	CHECK(note.start_ms == 0 && note.end_ms == 40);
	CHECK(pacing_note_at(&settings, 0, 20, &note) && note.active && note.tail == 0);
	settings.short_threshold_ms = 40; /* Strictly shorter, not <=. */
	CHECK(pacing_note_at(&settings, 0, 100, &note) && close_enough(note.tail, 50.9956));
	settings.delay_ms = 100;
	CHECK(!pacing_note_at(&settings, 0, 99, &note));
	CHECK(pacing_note_at(&settings, 0, 120, &note) && note.active);
	CHECK(close_enough(note.head, 16.998533333333334));
	int64_t first, last;
	pacing_note_range(&settings, 100000000, &first, &last);
	CHECK(first >= -3 && last - first < 4096);
	settings.green = 2000; settings.lift = 999; settings.sudden = 0;
	settings.overlay_height = 2160; settings.speed_scale = .25;
	pacing_note_range(&settings, 100000000, &first, &last);
	CHECK(last - first < 4096);
	struct pacing_clock clock = {0};
	pacing_clock_advance(&clock, 0);
	CHECK(!clock.ready && clock.elapsed_ms == 0);
	pacing_clock_advance(&clock, UINT64_C(1000000000));
	CHECK(clock.ready && clock.elapsed_ms == 0);
	pacing_clock_advance(&clock, UINT64_C(1016666667));
	CHECK(close_enough(clock.elapsed_ms, 16.666667));
	pacing_clock_advance(&clock, UINT64_C(1016666667));
	CHECK(close_enough(clock.elapsed_ms, 16.666667));
	pacing_clock_advance(&clock, UINT64_C(500000000));
	CHECK(close_enough(clock.elapsed_ms, 16.666667));
	pacing_clock_advance(&clock, UINT64_C(516666667));
	CHECK(close_enough(clock.elapsed_ms, 33.333334));
	return 0;
}

/* Snapshot ABI for cross-checking against the actual JavaScript renderer.
 * Returns note present=1/absent=0. out has x,width,head,tail,height,body,active,
 * start,end. Source timestamps remain unchanged for every visual variant.
 */
TEST_EXPORT int pacing_geometry_sample(double elapsed_ms, int variant, int index, double *out)
{
	struct pacing_settings settings = pacing_defaults();
	if (variant == 1) { settings.body_enabled = true; settings.short_enabled = false; }
	if (variant == 2) { settings.body_enabled = true; settings.short_percent = 30; settings.short_threshold_ms = 200; }
	if (variant == 3) { settings.body_enabled = true; settings.short_percent = 30; settings.short_threshold_ms = 40; }
	if (variant == 4) { settings.body_enabled = true; settings.delay_ms = 100; }
	if (variant == 5) settings.second_player = true;
	struct pacing_note note;
	if (!pacing_note_at(&settings, index, elapsed_ms, &note)) return 0;
	struct pacing_lane lane = pacing_lane(&settings, note.lane);
	out[0] = lane.x + 3; out[1] = lane.width - 6;
	out[2] = note.head; out[3] = note.tail; out[4] = settings.note_height;
	out[5] = note.body_enabled; out[6] = note.active;
	out[7] = note.start_ms; out[8] = note.end_ms;
	return 1;
}
