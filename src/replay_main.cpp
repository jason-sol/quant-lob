#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#include <cerrno>
#include <charconv>
#include <cstring>
#include <fstream>
#include <iostream>
#include <memory>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "qlob/replay.hpp"

namespace {
constexpr int kUsageError = 2;
constexpr int kOutputError = 1;
constexpr std::size_t kMaxDepth = 1000;

struct Args {
  std::string file;
  std::size_t depth = 5;
  std::optional<std::string> snapshots;
  bool count = false;
};

std::optional<Args> parse(int argc, char** argv) {
  Args a;
  bool have_file = false;
  for (int i = 1; i < argc; ++i) {
    const std::string_view arg = argv[i];
    if (arg == "--count") {
      a.count = true;
    } else if (arg == "--depth" || arg == "--snapshots") {
      if (++i >= argc) return std::nullopt;
      const std::string_view val = argv[i];
      if (arg == "--snapshots") {
        a.snapshots = std::string(val);
        continue;
      }
      const auto [end, ec] = std::from_chars(val.data(), val.data() + val.size(), a.depth);
      if (ec != std::errc{} || end != val.data() + val.size() || a.depth == 0 || a.depth > kMaxDepth) {
        return std::nullopt;
      }
    } else if (!have_file && !arg.starts_with("--")) {
      a.file = arg;
      have_file = true;
    } else {
      return std::nullopt;
    }
  }
  if (!have_file || (a.count && a.snapshots)) return std::nullopt;
  return a;
}

// Read-only mapping of the whole file; a 0-byte file maps to an empty span without mmap.
class MappedFile {
 public:
  // On failure returns nullptr and sets `error`.
  static std::unique_ptr<MappedFile> open(const std::string& path, std::string& error) {
    const int fd = ::open(path.c_str(), O_RDONLY);
    if (fd < 0) {
      error = std::strerror(errno);
      return nullptr;
    }
    const auto fail = [&](std::string why) {
      ::close(fd);
      error = std::move(why);
      return nullptr;
    };
    struct stat st {};
    if (::fstat(fd, &st) != 0) return fail(std::strerror(errno));
    if (!S_ISREG(st.st_mode)) return fail("not a regular file");
    const auto size = static_cast<std::size_t>(st.st_size);
    void* addr = nullptr;
    if (size > 0) {
      addr = ::mmap(nullptr, size, PROT_READ, MAP_PRIVATE, fd, 0);
      if (addr == MAP_FAILED) return fail(std::strerror(errno));
      ::madvise(addr, size, MADV_SEQUENTIAL);
    }
    ::close(fd);
    return std::unique_ptr<MappedFile>(new MappedFile(addr, size));
  }
  ~MappedFile() {
    if (addr_) ::munmap(addr_, size_);
  }
  MappedFile(const MappedFile&) = delete;
  MappedFile& operator=(const MappedFile&) = delete;
  std::span<const std::byte> bytes() const { return {static_cast<const std::byte*>(addr_), size_}; }

 private:
  MappedFile(void* addr, std::size_t size) : addr_(addr), size_(size) {}
  void* addr_;
  std::size_t size_;
};
}  // namespace

int main(int argc, char** argv) {
  std::ios::sync_with_stdio(false);
  const auto args = parse(argc, argv);
  if (!args) {
    std::cerr << "usage: qlob_replay <file> [--depth N] [--snapshots <path>|-] [--count]\n";
    return kUsageError;
  }
  std::string error;
  const auto file = MappedFile::open(args->file, error);
  if (!file) {
    std::cerr << "qlob_replay: cannot read " << args->file << ": " << error << '\n';
    return kUsageError;
  }

  if (args->count) {
    qlob::write_counts(qlob::scan(file->bytes()), std::cout);
    std::cout.flush();
    return std::cout ? 0 : kOutputError;
  }

  std::vector<char> file_buffer;
  std::ofstream csv;
  std::ostream* snapshots = nullptr;
  if (args->snapshots == "-") {
    snapshots = &std::cout;
  } else if (args->snapshots) {
    file_buffer.resize(1 << 20);
    csv.rdbuf()->pubsetbuf(file_buffer.data(), static_cast<std::streamsize>(file_buffer.size()));
    csv.open(*args->snapshots, std::ios::binary | std::ios::trunc);
    if (!csv) {
      std::cerr << "qlob_replay: cannot write " << *args->snapshots << '\n';
      return kUsageError;
    }
    snapshots = &csv;
  }

  const auto result = qlob::replay(file->bytes(), args->depth, snapshots);
  if (snapshots) snapshots->flush();
  qlob::write_summary(result, std::cerr);
  if (snapshots && !*snapshots) {
    std::cerr << "qlob_replay: failed writing snapshots\n";
    return kOutputError;
  }
  return 0;
}
