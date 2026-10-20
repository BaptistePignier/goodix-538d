// SIGFM with tunable parameters, to explore them offline.
//
// usage: sigfm_tune <scale> <contrast> <ratio> <min_match> <length_tol>
//                   <angle_tol> <image.pgm>...
// Same algorithm as libfprint/sigfm/sigfm.cpp (sigfm_extract and
// sigfm_match_score), whose constants are: SIFT contrast threshold 0.04
// (OpenCV default), ratio 0.75, min_match 5, length and angle tolerance 0.05.
// Output: same CSV as sigfm_matrix.
//
// Build: g++ -O2 -std=c++17 sigfm_tune.cpp $(pkg-config --cflags --libs opencv4)
#include <opencv2/opencv.hpp>
#include <cmath>
#include <cstdlib>
#include <cstdio>
#include <set>
#include <string>
#include <vector>

struct Params {
    double scale, contrast, ratio, length_tol, angle_tol;
    std::size_t min_match;
};

struct Info {
    std::vector<cv::KeyPoint> keypoints;
    cv::Mat descriptors;
};

// libsigfm's match::operator< only compares p1.y, so its std::set keeps a
// single match per row of the verified image. $SIGFM_ROW_BUG=1 reproduces it.
static bool row_bug = false;

struct Match {
    cv::Point2i p1, p2;
    bool operator<(const Match& o) const
    {
        if (row_bug) {
            return p1.y < o.p1.y;
        }
        return std::tie(p1.x, p1.y, p2.x, p2.y) <
               std::tie(o.p1.x, o.p1.y, o.p2.x, o.p2.y);
    }
};

struct Angle {
    double cos, sin;
};

static Info extract(const cv::Mat& img, const Params& params)
{
    Info info;
    cv::SIFT::create(0, 3, params.contrast)
        ->detectAndCompute(img, cv::noArray(), info.keypoints, info.descriptors);
    return info;
}

static int match_score(const Info& frame, const Info& enrolled, const Params& params)
{
    if (frame.descriptors.empty() || enrolled.descriptors.empty()) {
        return 0;
    }
    std::vector<std::vector<cv::DMatch>> points;
    cv::BFMatcher().knnMatch(frame.descriptors, enrolled.descriptors, points, 2);

    std::set<Match> unique;
    std::size_t matched = 0;
    for (const auto& pts : points) {
        if (pts.size() < 2) {
            continue;
        }
        if (pts[0].distance < params.ratio * pts[1].distance) {
            unique.insert(Match{frame.keypoints[pts[0].queryIdx].pt,
                                enrolled.keypoints[pts[0].trainIdx].pt});
            matched++;
        }
    }
    if (matched < params.min_match) {
        return 0;
    }

    std::vector<Match> matches(unique.begin(), unique.end());
    std::vector<Angle> angles;
    for (std::size_t j = 0; j < matches.size(); j++) {
        for (std::size_t k = j + 1; k < matches.size(); k++) {
            const int v1[2] = {matches[j].p1.x - matches[k].p1.x,
                               matches[j].p1.y - matches[k].p1.y};
            const int v2[2] = {matches[j].p2.x - matches[k].p2.x,
                               matches[j].p2.y - matches[k].p2.y};
            const double l1 = std::hypot(v1[0], v1[1]);
            const double l2 = std::hypot(v2[0], v2[1]);
            if (1 - std::min(l1, l2) / std::max(l1, l2) <= params.length_tol) {
                const double product = l1 * l2;
                angles.push_back(Angle{
                    M_PI / 2 + std::asin((v1[0] * v2[0] + v1[1] * v2[1]) / product),
                    std::acos((v1[0] * v2[1] - v1[1] * v2[0]) / product)});
            }
        }
    }
    if (angles.size() < params.min_match) {
        return 0;
    }

    int count = 0;
    for (std::size_t j = 0; j < angles.size(); j++) {
        for (std::size_t k = j + 1; k < angles.size(); k++) {
            if (1 - std::min(angles[j].sin, angles[k].sin) /
                            std::max(angles[j].sin, angles[k].sin) <= params.angle_tol &&
                1 - std::min(angles[j].cos, angles[k].cos) /
                            std::max(angles[j].cos, angles[k].cos) <= params.angle_tol) {
                count++;
            }
        }
    }
    return count;
}

int main(int argc, char** argv)
{
    if (argc < 8) {
        std::fprintf(stderr, "usage: %s <scale> <contrast> <ratio> <min_match> "
                             "<length_tol> <angle_tol> <image.pgm>...\n", argv[0]);
        return 1;
    }
    row_bug = std::getenv("SIGFM_ROW_BUG") != nullptr;
    const Params params{std::stod(argv[1]), std::stod(argv[2]), std::stod(argv[3]),
                        std::stod(argv[5]), std::stod(argv[6]),
                        static_cast<std::size_t>(std::stoul(argv[4]))};

    std::vector<Info> infos;
    for (int i = 7; i < argc; ++i) {
        cv::Mat img = cv::imread(argv[i], cv::IMREAD_GRAYSCALE);
        if (img.empty()) {
            std::fprintf(stderr, "cannot read %s\n", argv[i]);
            return 1;
        }
        if (params.scale != 1.0) {
            cv::resize(img, img, cv::Size(), params.scale, params.scale, cv::INTER_CUBIC);
        }
        infos.push_back(extract(img, params));
    }

    for (std::size_t p = 0; p < infos.size(); ++p) {
        std::printf("%zu", infos[p].keypoints.size());
        for (std::size_t t = 0; t < infos.size(); ++t) {
            std::printf(",%d", p == t ? -1 : match_score(infos[p], infos[t], params));
        }
        std::printf("\n");
    }
}
