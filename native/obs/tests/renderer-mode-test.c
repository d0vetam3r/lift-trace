/* SPDX-License-Identifier: MIT
 * Compile with an OBS SDK, but link/run only the mock graphics boundary.
 * This does not load OBS or access a controller. The explicit experiment macro
 * tests the retained benchmark build; without it the live build must be silent.
 */
#include <obs-module.h>
#undef OBS_DECLARE_MODULE
#undef MODULE_EXPORT
#define OBS_DECLARE_MODULE()
#define MODULE_EXPORT

static unsigned draws;
static bool loop_on;
static void mock_color(gs_eparam_t *param, const struct vec4 *color)
{ (void)param; (void)color; }
static void mock_matrix(void) {}
static void mock_transform(float x, float y, float z)
{ (void)x; (void)y; (void)z; }
static bool mock_loop(gs_effect_t *effect, const char *name)
{ (void)effect; (void)name; loop_on = !loop_on; return loop_on; }
static void mock_draw(gs_texture_t *texture, uint32_t flip, uint32_t width, uint32_t height)
{ (void)texture; (void)flip; (void)width; (void)height; ++draws; }
static void mock_render_start(bool fresh) { (void)fresh; }
static void mock_vertex(float x, float y) { (void)x; (void)y; }
static void mock_render_stop(enum gs_draw_mode mode) { (void)mode; }

#define gs_effect_set_vec4 mock_color
#define gs_matrix_push mock_matrix
#define gs_matrix_pop mock_matrix
#define gs_matrix_translate3f mock_transform
#define gs_matrix_scale3f mock_transform
#define gs_effect_loop mock_loop
#define gs_draw_sprite mock_draw
#define gs_render_start mock_render_start
#define gs_vertex2f mock_vertex
#define gs_render_stop mock_render_stop

#ifdef LIFT_NATIVE_SYNTHETIC
#include "../../../experiments/obs-native-pacing/pacing-geometry.h"
#endif
#include "../lift-native-pacing.c"

#ifdef _WIN32
#define TEST_EXPORT __declspec(dllexport)
#else
#define TEST_EXPORT __attribute__((visibility("default")))
#endif
#define CHECK(value) do { if (!(value)) return __LINE__; } while (0)

TEST_EXPORT int lift_renderer_mode_tests(void)
{
    struct painter painter = {0};
    struct pacing_snapshot frame = {0};
    static struct lift_live_packet packet;
    frame.settings = pacing_defaults();
    frame.settings.guides = false;
    frame.settings.transparent = true;
    frame.elapsed_ms = 100;
    draws = 0;
    overlay(&painter, &frame, &packet);
#ifdef LIFT_NATIVE_SYNTHETIC
    CHECK(draws > 0);
#else
    CHECK(draws == 0);
#endif
    /* Empty or stale live input never falls back to benchmark input. */
    frame.live = true;
    draws = 0;
    overlay(&painter, &frame, &packet);
    CHECK(draws == 0);
    frame.live_valid = true;
    frame.live_now_ms = 1100;
    packet.count = 0;
    overlay(&painter, &frame, &packet);
    CHECK(draws == 0);
    packet.count = 1;
    packet.events[0] = (struct lift_live_event){1, 0, 1000.125, 1040.375};
    overlay(&painter, &frame, &packet);
    CHECK(draws == 1);
    CHECK(packet.events[0].start_ms == 1000.125 && packet.events[0].end_ms == 1040.375);
    draws = 0;
    frame.settings.body_enabled = true;
    overlay(&painter, &frame, &packet);
    CHECK(draws == 3);
    frame.live_valid = false;
    draws = 0;
    overlay(&painter, &frame, &packet);
    CHECK(draws == 0);
    return 0;
}
