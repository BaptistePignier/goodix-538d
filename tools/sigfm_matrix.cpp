// SIGFM score of every pair of images, with the libfprint SIGFM library.
//
// usage: sigfm_matrix <scale> <image.pgm>...
// Prints one CSV line per image: its keypoint count, then the score of that
// image (as the verified frame) against every image (as the enrolled one).
// Images are upscaled by <scale> with bicubic interpolation first.
//
// Build: g++ -O2 -std=c++17 -I<libfprint-sigfm>/libfprint/sigfm sigfm_matrix.cpp
//        <build>/libfprint/sigfm/libsigfm.a $(pkg-config --cflags --libs opencv4)
#include <opencv2/opencv.hpp>
#include <cstdio>
#include <string>
#include <vector>

#include "sigfm.hpp"

int main(int argc, char** argv)
{
    if (argc < 3) {
        std::fprintf(stderr, "usage: %s <scale> <image.pgm>...\n", argv[0]);
        return 1;
    }

    const double scale = std::stod(argv[1]);
    std::vector<SigfmImgInfo*> infos;
    std::vector<int> keypoints;

    for (int i = 2; i < argc; ++i) {
        cv::Mat img = cv::imread(argv[i], cv::IMREAD_GRAYSCALE);
        if (img.empty()) {
            std::fprintf(stderr, "cannot read %s\n", argv[i]);
            return 1;
        }
        if (scale != 1.0) {
            cv::resize(img, img, cv::Size(), scale, scale, cv::INTER_CUBIC);
        }
        infos.push_back(sigfm_extract(img.data, img.cols, img.rows));
        std::vector<cv::KeyPoint> pts;
        cv::SIFT::create()->detect(img, pts);
        keypoints.push_back(pts.size());
    }

    for (std::size_t p = 0; p < infos.size(); ++p) {
        std::printf("%d", keypoints[p]);
        for (std::size_t t = 0; t < infos.size(); ++t) {
            std::printf(",%d", p == t ? -1 : sigfm_match_score(infos[p], infos[t]));
        }
        std::printf("\n");
    }

    for (auto* info : infos) {
        sigfm_free_info(info);
    }
}
