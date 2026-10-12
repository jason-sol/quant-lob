cmake_minimum_required(VERSION 3.25)
project(qlob LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
option(QLOB_SANITIZE "Build with ASan+UBSan" OFF)
if(QLOB_SANITIZE)
  add_compile_options(-fsanitize=address,undefined -fno-omit-frame-pointer)
  add_link_options(-fsanitize=address,undefined)
endif()

add_library(qlob src/itch.cpp src/book.cpp)
target_include_directories(qlob PUBLIC include)
target_compile_options(qlob PRIVATE -Wall -Wextra -Wpedantic -Werror)

add_executable(qlob_replay src/replay_main.cpp)
target_link_libraries(qlob_replay PRIVATE qlob)

include(CTest)
if(BUILD_TESTING)
  include(FetchContent)
  FetchContent_Declare(googletest
    URL https://github.com/google/googletest/archive/refs/tags/v1.15.2.tar.gz
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE)
  FetchContent_MakeAvailable(googletest)
  add_subdirectory(tests)
endif()
