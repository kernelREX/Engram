// Engram's bridge to the native plugin.
//
// This file has no `module` line on purpose, and must not get one. A native class declared
// inside a module is namespaced by it, so `module Engram` here would declare
// `Engram.EngramNative`, and RED4ext would look for an RTTI class by that name, find
// nothing and stop the game from starting. RTTI class names have no module prefix.
// Codeware and ArchiveXL keep their native declarations in a Global.reds for the same
// reason.
//
// The signatures below have to match what native/src/Main.cpp registers in
// PostRegisterTypes, exactly. tools/check_natives.py checks that they do.

// Jobs, because packing six megabytes and uploading it takes seconds and the menu calls in
// from the game's own thread. Start one, then ask how it is going each frame.
enum EngramJobState {
  Unknown = 0,
  Working = 1,
  Done = 2,
  Failed = 3,
}

// What a job was started to do, so the menu does not guess from its output.
enum EngramJobKind {
  None = 0,
  Share = 1,
  Fetch = 2,
  Write = 3,
}

public native class EngramNative extends IScriptable {
  public static native func Version() -> String
  public static native func SaveFolder() -> String
  public static native func SaveNames() -> array<String>

  public static native func StartShare(saveName: String, hours: Int32) -> Int32
  public static native func StartFetch(code: String) -> Int32
  public static native func StartWrite(fetchJob: Int32, force: Bool) -> Int32

  public static native func JobState(job: Int32) -> Int32
  public static native func JobKind(job: Int32) -> Int32
  public static native func JobModded(job: Int32) -> Bool
  public static native func JobMessage(job: Int32) -> String
  public static native func JobCode(job: Int32) -> String
  public static native func JobBlocked(job: Int32) -> Bool
  public static native func JobFindings(job: Int32) -> array<String>
  public static native func CancelJob(job: Int32) -> Void
  public static native func ForgetJobs() -> Void
}

// The menus call these rather than the natives directly, so there is one place to put the
// awkwardness if a signature ever has to change.
public class Engram {
  public static func Version() -> String {
    return EngramNative.Version();
  }

  // Whether the native half is present and answering. Everything the player can press sits
  // behind this, so a half installed mod shows nothing rather than failing mid press.
  public static func IsAvailable() -> Bool {
    return StrLen(EngramNative.Version()) > 0;
  }

  public static func SaveNames() -> array<String> {
    return EngramNative.SaveNames();
  }

  public static func StateOf(job: Int32) -> EngramJobState {
    switch EngramNative.JobState(job) {
      case 1: return EngramJobState.Working;
      case 2: return EngramJobState.Done;
      case 3: return EngramJobState.Failed;
      default: return EngramJobState.Unknown;
    };
  }

  public static func KindOf(job: Int32) -> EngramJobKind {
    switch EngramNative.JobKind(job) {
      case 1: return EngramJobKind.Share;
      case 2: return EngramJobKind.Fetch;
      case 3: return EngramJobKind.Write;
      default: return EngramJobKind.None;
    };
  }

  public static func Log(message: String) -> Void {
    FTLog(s"[Engram] \(message)");
  }
}
