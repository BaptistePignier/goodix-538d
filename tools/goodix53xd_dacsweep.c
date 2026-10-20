// Records the finger-free image of a goodix53xd for several DAC offsets.
//
// usage: sudo goodix53xd_dacsweep <output dir> <offset>...
// e.g.:  sudo goodix53xd_dacsweep dacsweep -100 -50 0 50 100
//
// For each offset, $GOODIX53XD_DAC_OFFSET is set, a capture is started so
// that the driver dumps its first calibration frame (no finger on the
// sensor, read at the offset + GOODIX53XD_DETECT_DAC_STEP) as
// <output dir>/<offset>/*-empty-detect.pgm, then the capture is cancelled.
//
// Build: same as goodix53xd_collect.c

#include <fprint.h>
#include <glib.h>
#include <glib/gstdio.h>
#include <stdio.h>
#include <stdlib.h>

#define CAPTURE_TIME 2500 // ms, enough for activation and calibration

typedef struct {
    GMainLoop* loop;
    GCancellable* cancellable;
} SweepData;

static void on_capture_done(GObject* source, GAsyncResult* res, gpointer user_data)
{
    SweepData* data = user_data;
    g_autoptr(GError) error = NULL;
    g_autoptr(FpImage) img =
        fp_device_capture_finish(FP_DEVICE(source), res, &error);

    if (img != NULL) {
        printf("    a finger was detected, run again without touching the sensor\n");
    }
    g_main_loop_quit(data->loop);
}

static gboolean on_timeout(gpointer user_data)
{
    SweepData* data = user_data;
    g_cancellable_cancel(data->cancellable);
    return G_SOURCE_REMOVE;
}

int main(int argc, char** argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: %s <output dir> <offset>...\n", argv[0]);
        return EXIT_FAILURE;
    }

    g_autoptr(FpContext) ctx = fp_context_new();
    GPtrArray* devices = fp_context_get_devices(ctx);
    if (devices == NULL || devices->len == 0) {
        fprintf(stderr, "No reader found (run with sudo?)\n");
        return EXIT_FAILURE;
    }
    FpDevice* dev = g_ptr_array_index(devices, 0);

    g_autoptr(GError) error = NULL;
    if (!fp_device_open_sync(dev, NULL, &error)) {
        fprintf(stderr, "Cannot open the reader: %s\n", error->message);
        return EXIT_FAILURE;
    }

    printf("Do not touch the sensor during the whole measurement.\n");
    for (int arg = 2; arg < argc; ++arg) {
        g_autofree gchar* dir = g_build_filename(argv[1], argv[arg], NULL);
        g_mkdir_with_parents(dir, 0755);
        g_setenv("GOODIX53XD_DUMP_DIR", dir, TRUE);
        g_setenv("GOODIX53XD_DAC_OFFSET", argv[arg], TRUE);
        printf("  offset %s\n", argv[arg]);
        fflush(stdout);

        SweepData data = {g_main_loop_new(NULL, FALSE), g_cancellable_new()};
        fp_device_capture(dev, TRUE, data.cancellable, on_capture_done, &data);
        g_timeout_add(CAPTURE_TIME, on_timeout, &data);
        g_main_loop_run(data.loop);
        g_main_loop_unref(data.loop);
        g_object_unref(data.cancellable);
    }

    fp_device_close_sync(dev, NULL, NULL);
    printf("Done.\n");
    return EXIT_SUCCESS;
}
