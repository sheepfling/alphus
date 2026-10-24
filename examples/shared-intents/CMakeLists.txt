cmake_minimum_required(VERSION 3.20)
project(alphus_shared_intents LANGUAGES CXX)

add_executable(function_complexity cpp/function_complexity.cpp)
target_compile_features(function_complexity PRIVATE cxx_std_20)
