// Agenten-Runde: kleines schwebendes Fenster fuer macOS.
// Zeigt die Oberflaeche, die huddle.pyw auf http://127.0.0.1:47811/ ausliefert.
// Bauen: xcrun swiftc -O panel.swift -o AgentenRunde   (macht install.py automatisch)
import Cocoa
import WebKit

final class Delegate: NSObject, NSApplicationDelegate, NSWindowDelegate,
                      WKScriptMessageHandler, WKNavigationDelegate {
    let url: URL
    let width: CGFloat = 340
    var window: NSPanel!
    var web: WKWebView!
    var front = ""   // zuletzt aktive andere App (fuer "Zum Terminal" ein-/ausklappen)

    init(url: URL) {
        self.url = url
    }

    func applicationDidFinishLaunching(_ note: Notification) {
        let vis = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        let h: CGFloat = 60
        let rect = NSRect(x: vis.maxX - width - 20, y: vis.maxY - h - 40, width: width, height: h)
        window = NSPanel(contentRect: rect, styleMask: [.titled, .closable, .utilityWindow],
                         backing: .buffered, defer: false)
        window.title = "Agenten-Runde"
        window.appearance = NSAppearance(named: .darkAqua)
        window.backgroundColor = NSColor(red: 0x12 / 255.0, green: 0x13 / 255.0, blue: 0x12 / 255.0, alpha: 1)
        window.level = .floating
        window.isFloatingPanel = true
        window.hidesOnDeactivate = false
        window.isReleasedWhenClosed = false
        window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        window.delegate = self

        let cfg = WKWebViewConfiguration()
        cfg.userContentController.add(self, name: "huddle")
        web = WKWebView(frame: window.contentView!.bounds, configuration: cfg)
        web.autoresizingMask = [.width, .height]
        web.setValue(false, forKey: "drawsBackground")
        web.navigationDelegate = self
        window.contentView!.addSubview(web)
        web.load(URLRequest(url: url))
        window.orderFrontRegardless()

        let me = ProcessInfo.processInfo.processIdentifier
        if let a = NSWorkspace.shared.frontmostApplication, a.processIdentifier != me {
            front = a.bundleURL?.path ?? ""
        }
        NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didActivateApplicationNotification, object: nil, queue: .main
        ) { note in
            guard let a = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication,
                  a.processIdentifier != me else { return }
            self.front = a.bundleURL?.path ?? ""
            self.pushFront()
        }
    }

    // Der Seite mitteilen, welche App vor dem Klick ins Widget aktiv war.
    func pushFront() {
        guard let d = try? JSONSerialization.data(withJSONObject: [front]),
              let s = String(data: d, encoding: .utf8) else { return }
        web.evaluateJavaScript("window.huddleFront = \(s)[0];", completionHandler: nil)
    }

    func webView(_ w: WKWebView, didFinish n: WKNavigation!) {
        pushFront()
    }

    // Die Seite meldet ihre Hoehe; das Fenster waechst nach unten mit.
    func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) {
        guard let n = m.body as? NSNumber else { return }
        let vis = (window.screen ?? NSScreen.main)?.visibleFrame
            ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        let content = min(max(CGFloat(truncating: n), 40), vis.height - 80)
        let frameH = window.frameRect(forContentRect: NSRect(x: 0, y: 0, width: width, height: content)).height
        var f = window.frame
        if abs(f.height - frameH) < 1 { return }
        f.origin.y += f.height - frameH
        f.size.height = frameH
        window.setFrame(f, display: true)
    }

    func retry() {
        DispatchQueue.main.asyncAfter(deadline: .now() + 1) { self.web.load(URLRequest(url: self.url)) }
    }

    func webView(_ w: WKWebView, didFailProvisionalNavigation n: WKNavigation!, withError e: Error) {
        retry()
    }

    func webView(_ w: WKWebView, didFail n: WKNavigation!, withError e: Error) {
        retry()
    }

    func windowWillClose(_ note: Notification) {
        NSApp.terminate(nil)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ app: NSApplication) -> Bool {
        return true
    }
}

let args = CommandLine.arguments
guard args.count > 1, let url = URL(string: args[1]) else {
    FileHandle.standardError.write("usage: AgentenRunde <url>\n".data(using: .utf8)!)
    exit(2)
}
let app = NSApplication.shared
let delegate = Delegate(url: url)
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
