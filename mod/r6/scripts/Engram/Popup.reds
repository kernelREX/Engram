// The Engram popup: pick a save and get a code, or type a code and take one.
//
// Built entirely in code on Codeware's custom popup controllers, so the mod ships no
// archive and needs no WolvenKit. The code box is the game's own input dialog rather than a
// hand built text widget, because the game's one already handles focus, the caret and the
// gamepad.

module Engram.Popup

import Engram.*
import Codeware.UI.*

enum EngramPage {
  Home = 0,
  Saves = 1,
  Code = 2,
  Busy = 3,
  Result = 4,
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
  private let m_pollProxy: ref<inkAnimProxy>;

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
    body.SetChildMargin(inkMargin(0.0, 6.0, 0.0, 6.0));
    body.SetHAlign(inkEHorizontalAlign.Left);
    body.SetMargin(inkMargin(40.0, 20.0, 40.0, 20.0));
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

  // ------------------------------------------------------------------ building the pages

  private func Clear() -> Void {
    this.m_body.RemoveAllChildren();
  }

  private func Line(text: String, opacity: Float) -> Void {
    let label = new inkText();
    label.SetText(text);
    label.SetFontFamily("base\\gameplay\\gui\\fonts\\raj\\raj.inkfontfamily");
    label.SetFontStyle(n"Medium");
    label.SetFontSize(32);
    label.SetOpacity(opacity);
    label.SetHAlign(inkEHorizontalAlign.Left);
    label.SetWrapping(true, 1200.0, textWrappingPolicy.Default);
    label.Reparent(this.m_body);
  }

  private func Say(text: String) -> Void {
    this.Line(text, 1.0);
  }

  private func Quiet(text: String) -> Void {
    this.Line(text, 0.6);
  }

  private func Button(label: String, name: CName) -> Void {
    let button = SimpleButton.Create();
    button.SetName(name);
    button.SetText(label);
    button.SetWidth(1200.0);
    button.Reparent(this.m_body);
    button.RegisterToCallback(n"OnBtnClick", this, n"OnButton");
  }

  private func GoHome() -> Void {
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
    }

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

  private func GoBusy(what: String) -> Void {
    this.m_page = EngramPage.Busy;
    this.Clear();
    this.Say(what);
    this.Quiet("This takes a moment. The game is not frozen.");
    this.StartPolling();
  }

  private func GoResult(title: String, detail: String) -> Void {
    this.m_page = EngramPage.Result;
    this.StopPolling();
    this.Clear();
    this.Say(title);
    if StrLen(detail) > 0 {
      this.Quiet(detail);
    };
    this.Button("Back", n"home");
  }

  // ------------------------------------------------------------------------- the buttons

  protected cb func OnButton(controller: wref<inkButtonController>) -> Bool {
    let widget = controller.GetRootWidget();
    let name = NameToString(widget.GetName());

    if Equals(name, "home") {
      this.GoHome();
      return true;
    };
    if Equals(name, "share") {
      this.GoSaves();
      return true;
    };
    if Equals(name, "receive") {
      this.AskForCode();
      return true;
    };
    if StrBeginsWith(name, "save:") {
      let index = StringToInt(StrAfterFirst(name, "save:"));
      if index >= 0 && index < ArraySize(this.m_saves) {
        this.m_picked = this.m_saves[index];
        this.m_job = EngramNative.StartShare(this.m_picked);
        this.GoBusy(s"Packing and uploading \(this.m_picked)");
      };
      return true;
    };
    return true;
  }

  private func AskForCode() -> Void {
    this.m_page = EngramPage.Code;
    this.Clear();
    this.Say("Type the code they read out.");
    this.Quiet("Case and dashes do not matter.");
    this.Button("Enter the code", n"enterCode");
    this.Button("Back", n"home");
  }

  // ------------------------------------------------------- watching a job without stalling

  private func StartPolling() -> Void {
    this.StopPolling();
    let options: inkAnimOptions;
    options.loopInfinite = true;
    options.loopType = inkanimLoopType.Cycle;

    let interpolator = new inkAnimTransparency();
    interpolator.SetStartTransparency(1.0);
    interpolator.SetEndTransparency(1.0);
    interpolator.SetDuration(0.25);

    let definition = new inkAnimDef();
    definition.AddInterpolator(interpolator);

    this.m_pollProxy = this.m_body.PlayAnimationWithOptions(definition, options);
    this.m_pollProxy.RegisterToCallback(inkanimEventType.OnEndLoop, this, n"OnPoll");
  }

  private func StopPolling() -> Void {
    if IsDefined(this.m_pollProxy) {
      this.m_pollProxy.UnregisterFromCallback(inkanimEventType.OnEndLoop, this, n"OnPoll");
      this.m_pollProxy.Stop();
      this.m_pollProxy = null;
    };
  }

  protected cb func OnPoll(proxy: ref<inkAnimProxy>) -> Bool {
    if NotEquals(this.m_page, EngramPage.Busy) || this.m_job == 0 {
      return true;
    };

    switch Engram.StateOf(this.m_job) {
      case EngramJobState.Done:
        let code = EngramNative.JobCode(this.m_job);
        if StrLen(code) > 0 {
          this.GoResult(code, "Read that out. It is the whole thing the other person needs.");
        } else {
          this.GoResult("Done", EngramNative.JobMessage(this.m_job));
        };
        break;
      case EngramJobState.Failed:
        this.GoResult("That did not work", EngramNative.JobMessage(this.m_job));
        break;
      default:
        break;
    };
    return true;
  }
}
