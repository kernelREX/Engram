#pragma once

#include <cstdint>
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
struct JobReport
{
    JobState state = JobState::Unknown;
    std::string message;
    std::string code;
    std::vector<std::string> findings;
    bool blocked = false;
};

// Start packing and uploading a save. Returns a job id, or 0 if it could not start.
int32_t StartShare(const std::string& aSaveName);

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
