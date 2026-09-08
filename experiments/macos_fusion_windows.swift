// =============================================================================
// DEVELOPMENT-ONLY EXTERNAL UI DISCOVERY — SECURITY AND PRIVACY BOUNDARY
//
// This helper is invoked only by the explicit QA --desktop-ui option. It does not
// capture pixels, accept a process/window/rectangle argument, or run with the add-in.
// It returns metadata only for visible layer-zero windows whose Core Graphics owner
// is exactly "Fusion". Python then requires the PID to match Autodesk Fusion's exact
// executable and bundle metadata before any exact-window capture can occur.
// =============================================================================

import CoreGraphics
import Foundation

let options: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
guard let rawWindows = CGWindowListCopyWindowInfo(options, kCGNullWindowID)
    as? [[String: Any]]
else {
    FileHandle.standardError.write(Data("Core Graphics returned no window inventory.\n".utf8))
    exit(1)
}

var windows: [[String: Any]] = []
for rawWindow in rawWindows {
    guard
        let ownerName = rawWindow[kCGWindowOwnerName as String] as? String,
        ownerName == "Fusion",
        let ownerPidNumber = rawWindow[kCGWindowOwnerPID as String] as? NSNumber,
        let windowIdNumber = rawWindow[kCGWindowNumber as String] as? NSNumber,
        let layerNumber = rawWindow[kCGWindowLayer as String] as? NSNumber,
        layerNumber.intValue == 0,
        let bounds = rawWindow[kCGWindowBounds as String] as? [String: Any],
        let xNumber = bounds["X"] as? NSNumber,
        let yNumber = bounds["Y"] as? NSNumber,
        let widthNumber = bounds["Width"] as? NSNumber,
        let heightNumber = bounds["Height"] as? NSNumber,
        widthNumber.doubleValue > 0,
        heightNumber.doubleValue > 0
    else {
        continue
    }
    let ownerPid = ownerPidNumber.intValue
    let windowId = windowIdNumber.intValue
    let title = rawWindow[kCGWindowName as String] as? String ?? ""
    let x = xNumber.doubleValue
    let y = yNumber.doubleValue
    let width = widthNumber.doubleValue
    let height = heightNumber.doubleValue
    windows.append([
        "ownerName": ownerName,
        "ownerPid": ownerPid,
        "title": title,
        "windowId": windowId,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
    ])
}

let output = try JSONSerialization.data(withJSONObject: windows, options: [.sortedKeys])
FileHandle.standardOutput.write(output)
FileHandle.standardOutput.write(Data("\n".utf8))
