// The Engram popup: pick a save and get a code, or type a code and take one.
//
// Built entirely in code on Codeware's custom popup controllers, so the mod ships no
// archive and needs no WolvenKit. The code box is the game's own input dialog rather than a
// hand built text widget, because the game's one already handles focus, the caret and the
// gamepad.
//
// Nothing here does any work itself. Every button starts a job in the native plugin and
// watches it, because packing six megabytes and uploading it would otherwise stall the
// frame the player is looking at.

module Engram.Popup

import Codeware.UI.*

enum EngramPage {
  Home = 0,
  Saves = 1,
  Expiry = 2,
  Busy = 3,
  Shared = 4,
  Incoming = 5,
  Written = 6,
  Failed = 7,
}

public class EngramPopup extends InMenuPopup {
  private let m_content: ref<InMenuPopupContent>;
  private let m_body: wref<inkVerticalPanel>;
  private let m_page: EngramPage;
  private let m_saves: array<String>;
  private let m_picked: String;
  private let m_job: Int32;
  private let m_fetchJob: Int32;
  private let m_requester: wref<inkGameController>;
  private let m_poll: ref<inkAnimProxy>;
  private let m_token: ref<inkGameNotificationToken>;

  public static func Show(requester: ref<inkGameController>) -> Void {
    let popup = new EngramPopup();
    popup.m_requester = requester;
    popup.Open(requester);
  }

  protected cb func OnCreate() {
    super.OnCreate();

    this.m_content = InMenuPopupContent.Create();
    this.m_content.SetTitle("ENGRAM");
    this.m_content.Reparent(this);

    let body = new inkVerticalPanel();
    body.SetName(n"engramBody");
    body.SetFitToContent(true);
    body.SetChildMargin(inkMargin(0.0, 5.0, 0.0, 5.0));
    body.SetHAlign(inkEHorizontalAlign.Left);
    body.SetMargin(inkMargin(40.0, 16.0, 40.0, 16.0));
    body.Reparent(this.m_content.GetContainerWidget());
    this.m_body = body;

    let footer = InMenuPopupFooter.Create();
    footer.Reparent(this);

    let close = PopupButton.Create();
    close.SetText("Close");
    close.SetInputAction(n"cancel");
    close.Reparent(footer);

    this.GoHome();
  }

  protected cb func OnDetach() {
    super.OnDetach();
    this.StopPolling();
    EngramNative.ForgetJobs();
  }

  protected cb func OnCancel() {
    this.Close();
  }

  // ------------------------------------------------------------------ drawing the pages

  private func Clear() -> Void {
    this.m_body.RemoveAllChildren();
  }

  private func Line(text: String, size: Int32, opacity: Float, colour: String) -> Void {
    let label = new inkText();
    label.SetText(text);
    label.SetFontFamily("base\\gameplay\\gui\\fonts\\raj\\raj.inkfontfamily");
    label.SetFontStyle(n"Medium");
    label.SetFontSize(size);
    label.SetOpacity(opacity);
    label.SetHAlign(inkEHorizontalAlign.Left);
    label.SetWrapping(true, 1180.0, textWrappingPolicy.Default);
    if StrLen(colour) > 0 {
      label.SetStyle(r"base\\gameplay\\gui\\common\\main_colors.inkstyle");
      label.BindProperty(n"tintColor", StringToName(colour));
    };
    label.Reparent(this.m_body);
  }

  private func Say(text: String) -> Void {
    this.Line(text, 32, 1.0, "");
  }

  private func Quiet(text: String) -> Void {
    this.Line(text, 26, 0.55, "");
  }

  private func Alert(text: String) -> Void {
    this.Line(text, 30, 1.0, "MainColors.Red");
  }

  private func Caution(text: String) -> Void {
    this.Line(text, 30, 1.0, "MainColors.ActiveYellow");
  }

  private func Headline(text: String) -> Void {
    this.Line(text, 42, 1.0, "MainColors.ActiveBlue");
  }

  private func Button(label: String, name: CName) -> Void {
    let button = SimpleButton.Create();
    button.SetName(name);
    button.SetText(label);
    button.SetWidth(1180.0);
    button.Reparent(this.m_body);
    button.RegisterToCallback(n"OnBtnClick", this, n"OnButton");
  }

  private func GoHome() -> Void {
    this.StopPolling();
    this.m_page = EngramPage.Home;
    this.Clear();
    this.Quiet("Move a save to another PC by reading out a code.");
    this.Button("Share a save", n"share");
    this.Button("Receive with a code", n"receive");
    this.Quiet(s"Engram \(Engram.Version())");
  }

  private func GoSaves() -> Void {
    this.m_page = EngramPage.Saves;
    this.Clear();
    this.m_saves = Engram.SaveNames();

    if ArraySize(this.m_saves) == 0 {
      this.Say("There are no saves on this machine yet.");
      this.Button("Back", n"home");
      return;
    };

    this.Quiet("Pick the save to share. Newest first.");
    let shown = Min(ArraySize(this.m_saves), 10);
    let i = 0;
    while i < shown {
      this.Button(this.m_saves[i], StringToName(s"save:\(i)"));
      i += 1;
    };
    if ArraySize(this.m_saves) > shown {
      this.Quiet(s"and \(ArraySize(this.m_saves) - shown) older save(s), not shown");
    };
    this.Button("Back", n"home");
  }

  // How long the code should keep working. Litterbox only accepts these four, so they are
  // what the sender is offered rather than a free number that the host would refuse.
  private func GoExpiry() -> Void {
    this.m_page = EngramPage.Expiry;
    this.Clear();
    this.Say(this.m_picked);
    this.Quiet("How long should the code keep working? It stops by itself afterwards, and");
    this.Quiet("the save is removed from the host. Shorter is safer.");
    this.Button("1 hour", n"hours:1");
    this.Button("12 hours", n"hours:12");
    this.Button("1 day", n"hours:24");
    this.Button("3 days, the longest", n"hours:72");
    this.Button("Back", n"share");
  }

  private func GoBusy(what: String) -> Void {
    this.m_page = EngramPage.Busy;
    this.Clear();
    this.Say(what);
    this.Quiet("This takes a moment. The game is not frozen.");
    this.StartPolling();
  }

  // The sender sees what is about to travel before they read the code out.
  private func GoShared(code: String) -> Void {
    this.StopPolling();
    this.m_page = EngramPage.Shared;
    this.Clear();

    this.Quiet("Read this out. It is the whole thing the other person needs.");
    this.Headline(code);
    this.Quiet(EngramNative.JobMessage(this.m_job));

    let findings = EngramNative.JobFindings(this.m_job);
    if ArraySize(findings) > 0 {
      this.Caution(findings[0]);
      let i = 1;
      while i < ArraySize(findings) && i < 26 {
        this.Quiet(findings[i]);
        i += 1;
      };
      if ArraySize(findings) > 26 {
        this.Quiet(s"and \(ArraySize(findings) - 26) more");
      };
    };

    this.Button("Done", n"home");
  }

  // The receiver sees the whole report, including what the save was made with.
  private func GoIncoming() -> Void {
    this.StopPolling();
    this.m_page = EngramPage.Incoming;
    this.m_fetchJob = this.m_job;
    this.Clear();

    this.Say(EngramNative.JobMessage(this.m_fetchJob));
    let blocked = EngramNative.JobBlocked(this.m_fetchJob);
    if blocked {
      this.Alert(EngramNative.JobCode(this.m_fetchJob));
    } else {
      this.Quiet(EngramNative.JobCode(this.m_fetchJob));
    };

    let findings = EngramNative.JobFindings(this.m_fetchJob);
    let i = 0;
    while i < ArraySize(findings) && i < 14 {
      this.DrawFinding(findings[i]);
      i += 1;
    };
    if ArraySize(findings) > 14 {
      this.Quiet(s"and \(ArraySize(findings) - 14) more");
    };

    if blocked {
      this.Quiet("Engram will not write this while the items marked STOP stand.");
      this.Button("Write it anyway", n"force");
    } else {
      this.Button("Write this save", n"write");
    };
    this.Button("Cancel", n"home");
  }

  // A finding arrives as "severity\tsummary\tdetail\titems", items joined by " | ".
  private func DrawFinding(line: String) -> Void {
    let parts = StrSplit(line, "\t");
    if ArraySize(parts) < 4 {
      this.Quiet(line);
      return;
    };

    let severity = StringToInt(parts[0]);
    if severity == 2 {
      this.Alert(s"STOP  \(parts[1])");
    } else {
      if severity == 1 {
        this.Caution(s"WARN  \(parts[1])");
      } else {
        this.Say(s"NOTE  \(parts[1])");
      };
    };

    if StrLen(parts[2]) > 0 {
      this.Quiet(s"      \(parts[2])");
    };
    if StrLen(parts[3]) > 0 {
      let items = StrSplit(parts[3], " | ");
      let i = 0;
      while i < ArraySize(items) && i < 12 {
        this.Quiet(s"      - \(items[i])");
        i += 1;
      };
      if ArraySize(items) > 12 {
        this.Quiet(s"      - and \(ArraySize(items) - 12) more");
      };
    };
  }

  private func GoWritten() -> Void {
    this.StopPolling();
    this.m_page = EngramPage.Written;
    this.Clear();
    this.Headline(EngramNative.JobCode(this.m_job));
    this.Say(EngramNative.JobMessage(this.m_job));
    this.Button("Done", n"home");
  }

  private func GoFailed() -> Void {
    this.StopPolling();
    this.m_page = EngramPage.Failed;
    this.Clear();
    this.Alert("That did not work");
    this.Say(EngramNative.JobMessage(this.m_job));
    this.Button("Back", n"home");
  }

  // ------------------------------------------------------------------------- the buttons

  protected cb func OnButton(controller: wref<inkButtonController>) -> Bool {
    let name = NameToString(controller.GetRootWidget().GetName());

    if Equals(name, "home") {
      this.GoHome();
    } else {
      if Equals(name, "share") {
        this.GoSaves();
      } else {
        if Equals(name, "receive") {
          this.AskForCode();
        } else {
          if Equals(name, "write") {
            this.m_job = EngramNative.StartWrite(this.m_fetchJob, false);
            this.GoBusy("Writing the save");
          } else {
            if Equals(name, "force") {
              this.m_job = EngramNative.StartWrite(this.m_fetchJob, true);
              this.GoBusy("Writing the save anyway");
            } else {
              if StrBeginsWith(name, "save:") {
                let index = StringToInt(StrAfterFirst(name, "save:"));
                if index >= 0 && index < ArraySize(this.m_saves) {
                  this.m_picked = this.m_saves[index];
                  this.GoExpiry();
                };
              } else {
                if StrBeginsWith(name, "hours:") {
                  let hours = StringToInt(StrAfterFirst(name, "hours:"));
                  this.m_job = EngramNative.StartShare(this.m_picked, hours);
                  this.GoBusy(s"Packing and uploading \(this.m_picked)");
                };
              };
            };
          };
        };
      };
    };
    return true;
  }

  // The game's own input dialog, which already handles focus, the caret and the gamepad.
  private func AskForCode() -> Void {
    this.m_token = GenericMessageNotification.ShowInput(
      this.m_requester,
      "ENGRAM",
      "Type the code they read out. Case and dashes do not matter.",
      GenericMessageNotificationType.ConfirmCancel);
    this.m_token.RegisterListener(this, n"OnCodeEntered");
  }

  protected cb func OnCodeEntered(data: ref<inkGameNotificationData>) -> Bool {
    let result = data as GenericMessageNotificationCloseData;
    this.m_token = null;
    if !IsDefined(result) || NotEquals(result.result, GenericMessageNotificationResult.Confirm) {
      return true;
    };

    let typed = result.input;
    if StrLen(typed) == 0 {
      return true;
    };

    this.m_job = EngramNative.StartFetch(typed);
    this.GoBusy("Fetching the save");
    return true;
  }

  // ------------------------------------------------------ watching a job without stalling

  private func StartPolling() -> Void {
    this.StopPolling();

    let interpolator = new inkAnimTransparency();
    interpolator.SetStartTransparency(1.0);
    interpolator.SetEndTransparency(1.0);
    interpolator.SetDuration(0.2);

    let definition = new inkAnimDef();
    definition.AddInterpolator(interpolator);

    let options: inkAnimOptions;
    options.loopInfinite = true;
    options.loopType = inkanimLoopType.Cycle;

    this.m_poll = this.m_body.PlayAnimationWithOptions(definition, options);
    this.m_poll.RegisterToCallback(inkanimEventType.OnEndLoop, this, n"OnPoll");
  }

  private func StopPolling() -> Void {
    if IsDefined(this.m_poll) {
      this.m_poll.UnregisterFromCallback(inkanimEventType.OnEndLoop, this, n"OnPoll");
      this.m_poll.Stop();
      this.m_poll = null;
    };
  }

  protected cb func OnPoll(proxy: ref<inkAnimProxy>) -> Bool {
    if NotEquals(this.m_page, EngramPage.Busy) || this.m_job == 0 {
      return true;
    };

    let state = Engram.StateOf(this.m_job);
    if Equals(state, EngramJobState.Failed) {
      this.GoFailed();
      return true;
    };
    if NotEquals(state, EngramJobState.Done) {
      return true;
    };

    switch Engram.KindOf(this.m_job) {
      case EngramJobKind.Share:
        this.GoShared(EngramNative.JobCode(this.m_job));
        break;
      case EngramJobKind.Fetch:
        this.GoIncoming();
        break;
      case EngramJobKind.Write:
        this.GoWritten();
        break;
      default:
        this.GoFailed();
        break;
    };
    return true;
  }
}
