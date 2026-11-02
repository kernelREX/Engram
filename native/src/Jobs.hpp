#pragma once

#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace engram
{
// Sharing a save packs six megabytes, derives a key and uploads it. Fetching one downloads
// and opens it. Either takes seconds, and the menu calls into this from the game's own
// thread, so nothing here is allowed to block: a job starts, the caller gets a number, and
// the menu asks how it is going on each frame.
enum class JobState : int32_t
{
    Unknown = 0,
    Working = 1,
    Done = 2,
    Failed = 3,
};

// What a job reports while it runs and once it stops. Every field is a copy, so reading it
// never races the worker.
// What a job was started to do, so the menu does not have to guess from its output.
enum class JobKind : int32_t
{
    None = 0,
    Share = 1,
    Fetch = 2,
    Write = 3,
};

struct JobReport
{
    JobState state = JobState::Unknown;
    JobKind kind = JobKind::None;
    std::string message;
    std::string code;
    std::vector<std::string> findings;
    bool blocked = false;
    bool modded = false;
};

// Where the game is installed, so the mod scan knows where to look. Set once at load.
void SetGameDir(const std::filesystem::path& aPath);

// Start packing and uploading a save, asking the host to keep it for `aHours`.
// Returns a job id, or 0 if it could not start.
int32_t StartShare(const std::string& aSaveName, int aHours);

// Start fetching and opening the save a code points at.
int32_t StartFetch(const std::string& aCode);

// Write a save a fetch job is holding. `aForce` goes ahead past the blocking findings.
int32_t StartWrite(int32_t aFetchJob, bool aForce);

JobReport Report(int32_t aJob);

// Give up on a job and let go of anything it is holding. Safe to call on a finished job,
// and safe to call twice.
void Cancel(int32_t aJob);

// Drop every finished job. Called when the menu closes, so a session's worth of fetched
// saves is not held in memory for the rest of the game.
void Forget();
} // namespace engram
