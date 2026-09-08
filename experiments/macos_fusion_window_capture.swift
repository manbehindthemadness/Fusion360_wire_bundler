// =============================================================================
// DEVELOPMENT-ONLY EXACT FUSION WINDOW CAPTURE — SECURITY AND PRIVACY BOUNDARY
//
// This helper is invoked only after the opted-in Python QA adapter has verified the
// Autodesk Fusion executable and bundle, matched Fusion Palette API bounds to a Core
// Graphics window, and created a private temporary directory. It accepts only that
// internally selected window ID, its already verified Fusion PID, and the private PNG
// path. It rechecks the Core Graphics owner, PID, and layer before exact-window capture.
// It never captures a screen or rectangle. Python deletes the PNG in a finally block.
// =============================================================================

import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

guard CommandLine.arguments.count == 4 else {
    FileHandle.standardError.write(Data("Expected window ID, Fusion PID, and output path.\n".utf8))
    exit(2)
}
guard
    let windowID = UInt32(CommandLine.arguments[1]),
    windowID > 0,
    let ownerPID = Int32(CommandLine.arguments[2]),
    ownerPID > 0
else {
    FileHandle.standardError.write(Data("Window ID and Fusion PID must be positive integers.\n".utf8))
    exit(2)
}

let rawWindows = CGWindowListCopyWindowInfo(
    [.optionIncludingWindow, .excludeDesktopElements],
    CGWindowID(windowID)
) as? [[String: Any]]
guard
    let rawWindow = rawWindows?.first,
    let actualWindowID = rawWindow[kCGWindowNumber as String] as? NSNumber,
    actualWindowID.uint32Value == windowID,
    let actualOwnerPID = rawWindow[kCGWindowOwnerPID as String] as? NSNumber,
    actualOwnerPID.int32Value == ownerPID,
    let ownerName = rawWindow[kCGWindowOwnerName as String] as? String,
    ownerName == "Fusion",
    let layer = rawWindow[kCGWindowLayer as String] as? NSNumber,
    layer.intValue == 0
else {
    FileHandle.standardError.write(Data("Window identity no longer matches verified Fusion.\n".utf8))
    exit(3)
}

guard let image = CGWindowListCreateImage(
    .null,
    .optionIncludingWindow,
    CGWindowID(windowID),
    [.boundsIgnoreFraming]
) else {
    FileHandle.standardError.write(Data("Core Graphics returned no exact-window image.\n".utf8))
    exit(4)
}

let outputURL = URL(fileURLWithPath: CommandLine.arguments[3])
guard let destination = CGImageDestinationCreateWithURL(
    outputURL as CFURL,
    UTType.png.identifier as CFString,
    1,
    nil
) else {
    FileHandle.standardError.write(Data("Could not create the private PNG destination.\n".utf8))
    exit(5)
}
CGImageDestinationAddImage(destination, image, nil)
guard CGImageDestinationFinalize(destination) else {
    FileHandle.standardError.write(Data("Could not encode the exact Fusion window as PNG.\n".utf8))
    exit(6)
}
do {
    try FileManager.default.setAttributes(
        [.posixPermissions: 0o600],
        ofItemAtPath: outputURL.path
    )
} catch {
    try? FileManager.default.removeItem(at: outputURL)
    FileHandle.standardError.write(Data("Could not restrict private PNG permissions.\n".utf8))
    exit(7)
}
