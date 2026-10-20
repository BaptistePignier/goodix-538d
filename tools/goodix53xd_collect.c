// Guided collection of goodix53xd presses for offline analysis.
//
// usage: sudo goodix53xd_collect <output dir> <label>:<count> [...]
// e.g.:  sudo goodix53xd_collect dataset index:30 majeur:10 pouce:10
//
// Each label gets its own sub directory, filled by the driver debug dumps
// ($GOODIX53XD_DUMP_DIR): raw frames, background, final image and contact
// delta of every accepted press. Presses rejected by the driver (too light,
// finger lifted too early) are asked again.
//
// Build against a libfprint build directory <b> and source tree <s>:
//   gcc -o goodix53xd_collect goodix53xd_collect.c -I<s>/libfprint -I<b>/libfprint
//       $(pkg-config --cflags --libs glib-2.0 gobject-2.0 gio-2.0 gusb)
//       -L<b>/libfprint -lfprint-2 -Wl,-rpath,<b>/libfprint

#include <fprint.h>
#include <glib.h>
#include <glib/gstdio.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_DEVICE_ERRORS 3 // consecutive, before giving up

static guint count_images(const gchar* dir)
{
    g_autoptr(GDir) d = g_dir_open(dir, 0, NULL);
    const gchar* name;
    guint count = 0;

    if (d == NULL) {
        return 0;
    }
    while ((name = g_dir_read_name(d)) != NULL) {
        if (g_str_has_suffix(name, "-image.pgm")) {
            count++;
        }
    }
    return count;
}

static void wait_enter(void)
{
    int c;
    while ((c = getchar()) != '\n' && c != EOF) {
    }
}

int main(int argc, char** argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: %s <output dir> <label>:<count> [...]\n",
                argv[0]);
        return EXIT_FAILURE;
    }

    const gchar* out_dir = argv[1];
    g_mkdir_with_parents(out_dir, 0755);

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
    printf("Reader: %s\n", fp_device_get_name(dev));

    for (int arg = 2; arg < argc; ++arg) {
        g_auto(GStrv) parts = g_strsplit(argv[arg], ":", 2);
        if (parts[0] == NULL || parts[1] == NULL) {
            fprintf(stderr, "Argument invalide : %s\n", argv[arg]);
            continue;
        }
        const gchar* label = parts[0];
        const guint wanted = (guint) g_ascii_strtoull(parts[1], NULL, 10);

        g_autofree gchar* label_dir = g_build_filename(out_dir, label, NULL);
        g_mkdir_with_parents(label_dir, 0755);
        // The driver reads it before every dump
        g_setenv("GOODIX53XD_DUMP_DIR", label_dir, TRUE);

        printf("\n=== Finger \"%s\": %u presses. Press Enter when ready.\n",
               label, wanted);
        wait_enter();

        guint done = count_images(label_dir);
        guint device_errors = 0;
        while (done < wanted) {
            printf("[%s %u/%u] Wait 1 second (finger-free image), place the "
                   "finger, then lift it.\n",
                   label, done + 1, wanted);
            fflush(stdout);

            g_clear_error(&error);
            g_autoptr(FpImage) img =
                fp_device_capture_sync(dev, TRUE, NULL, &error);
            const guint now = count_images(label_dir);

            if (now > done) {
                printf("    ok\n");
            }
            else if (error != NULL &&
                     !g_error_matches(error, FP_DEVICE_RETRY,
                                      error->code)) {
                // Not a bad press: give a transient error (e.g. the first
                // command after opening timing out) a few chances, but don't
                // loop on a persistent one
                if (++device_errors >= MAX_DEVICE_ERRORS) {
                    fprintf(stderr, "Reader error: %s\n", error->message);
                    fp_device_close_sync(dev, NULL, NULL);
                    return EXIT_FAILURE;
                }
                printf("    reader error (%s), trying again\n",
                       error->message);
                g_usleep(2 * G_USEC_PER_SEC);
                continue;
            }
            else if (error != NULL) {
                printf("    rejected (%s), press again\n", error->message);
            }
            device_errors = 0;
            done = now;
        }
    }

    g_clear_error(&error);
    fp_device_close_sync(dev, NULL, &error);
    printf("\nDone. Data in %s\n", out_dir);
    return EXIT_SUCCESS;
}
