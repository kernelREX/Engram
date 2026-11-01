// Engram, the redscript half.
//
// redscript owns the menus and nothing else. It cannot open a file or a socket, so every
// line here that does real work is a call into the native plugin in red4ext/plugins/Engram.
// The signatures below have to match what native/src/Main.cpp registers, exactly, or the
// game refuses to compile any script and starts with every mod disabled.

module Engram

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

  public static native func StartShare(saveName: String) -> Int32
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
