#pragma once

namespace engram
{
// Kept in step with engram/__init__.py. The two implementations share a container format,
// so a version that disagrees is worth noticing.
inline constexpr const char* kVersion = "1.0.0";

// The same string, reachable from the places that only include Code.hpp.
inline constexpr const char* kEngramVersion = "1.0.0";
} // namespace engram
