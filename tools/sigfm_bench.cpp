// Offline SIGFM benchmark on dumped goodix53xd images.
// usage: sigfm_bench <dataset dir> <first impostor index> <count>
// Images are goodix53xd-NNN.pgm as dumped with GOODIX53XD_DUMP_DIR. Images
// 0..4 of the genuine finger are the enrolled template, the other genuine
// images are probes, impostor images are compared to the template.
// Build: g++ -O2 -std=c++17 -I<libfprint-sigfm>/libfprint/sigfm sigfm_bench.cpp
//        <build>/libfprint/sigfm/libsigfm.a $(pkg-config --cflags --libs opencv4)
#include <opencv2/opencv.hpp>
#include <cstdio>
#include <string>
#include <vector>

extern "C" {
#include "sigfm.hpp"
}

static const int kEnrolled = 5;
static const int kThreshold = 24;

int main(int argc, char** argv)
{
    const std::string dir = argv[1];
    const int first_impostor = std::stoi(argv[2]);
    const int count = std::stoi(argv[3]);

    for (int scale : {1, 2, 3}) {
        std::vector<SigfmImgInfo*> infos;
        std::vector<int> keypoints;
        for (int i = 0; i < count; ++i) {
            char name[64];
            std::snprintf(name, sizeof(name), "/goodix53xd-%03d.pgm", i);
            cv::Mat img = cv::imread(dir + name, cv::IMREAD_GRAYSCALE);
            cv::Mat big;
            cv::resize(img, big, cv::Size(), scale, scale, cv::INTER_CUBIC);
            infos.push_back(sigfm_extract(big.data, big.cols, big.rows));
            std::vector<cv::KeyPoint> pts;
            cv::SIFT::create()->detect(big, pts);
            keypoints.push_back(pts.size());
        }

        int min_kp = 1 << 30;
        for (int k : keypoints) min_kp = std::min(min_kp, k);
        std::printf("== scale x%d (min keypoints %d)\n", scale, min_kp);

        int genuine_ok = 0, genuine = 0, impostor_ok = 0, impostor = 0;
        for (int p = kEnrolled; p < count; ++p) {
            int best = 0;
            std::string scores;
            for (int t = 0; t < kEnrolled; ++t) {
                const int s = sigfm_match_score(infos[p], infos[t]);
                best = std::max(best, s);
                scores += std::to_string(s) + " ";
            }
            const bool is_genuine = p < first_impostor;
            const bool match = best >= kThreshold;
            if (is_genuine) { genuine++; genuine_ok += match; }
            else { impostor++; impostor_ok += match; }
            std::printf("  probe %02d %s best %4d [ %s]\n", p,
                        is_genuine ? "genuine " : "impostor", best,
                        scores.c_str());
        }
        std::printf("  genuine accepted %d/%d, impostor accepted %d/%d\n",
                    genuine_ok, genuine, impostor_ok, impostor);

        for (auto* info : infos) sigfm_free_info(info);
    }
}
