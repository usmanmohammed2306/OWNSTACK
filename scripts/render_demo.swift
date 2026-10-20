// Offline macOS renderer. Actual screenshots + disclosed system-voice narration.
// No screen capture, microphone, network, inference, upload or publication.
import AppKit
import AVFoundation
import CoreVideo
import Foundation

struct Scene: Decodable {
    let image: String
    let title: String
    let caption: String
    let narration: String
}
struct RenderError: Error { let message: String }
func require(_ ok: Bool, _ message: String) throws {
    if !ok { throw RenderError(message: message) }
}
func render() async throws {
let args = CommandLine.arguments
try require(args.count == 4, "Usage: swift scripts/render_demo.swift <repo-root> <scene-json> <new-output-dir>")
let root = URL(fileURLWithPath: args[1]).standardizedFileURL
let manifest = URL(fileURLWithPath: args[2])
let output = URL(fileURLWithPath: args[3]).standardizedFileURL
let fm = FileManager.default
try require(!fm.fileExists(atPath: output.path), "Choose a new directory; existing media is never overwritten")
let scenes = try JSONDecoder().decode([Scene].self, from: Data(contentsOf: manifest))
try require(!scenes.isEmpty, "No scenes")
try fm.createDirectory(at: output, withIntermediateDirectories: true)
var audioURLs: [URL] = []
var durations: [Double] = []
for (index, scene) in scenes.enumerated() {
    let input = output.appendingPathComponent("narration-\(index + 1).txt")
    let audio = output.appendingPathComponent("narration-\(index + 1).aiff")
    try scene.narration.write(to: input, atomically: true, encoding: .utf8)
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/bin/say")
    process.arguments = ["-v", "Samantha", "-r", "185", "-f", input.path, "-o", audio.path]
    try process.run()
    process.waitUntilExit()
    try require(process.terminationStatus == 0, "System narration failed")
    let duration = try await AVURLAsset(url: audio).load(.duration).seconds
    try require(duration.isFinite && duration > 0, "Invalid narration duration")
    audioURLs.append(audio)
    durations.append(ceil(duration + 1.5))
}
let total = durations.reduce(0, +)
try require(total < 180, "Narration is \(total)s; shorten before publishing")
let silent = output.appendingPathComponent("screens.mp4")
let writer = try AVAssetWriter(outputURL: silent, fileType: .mp4)
let width = 1920, height = 1080, fps = 2
let input = AVAssetWriterInput(mediaType: .video, outputSettings: [
    AVVideoCodecKey: AVVideoCodecType.h264,
    AVVideoWidthKey: width, AVVideoHeightKey: height,
    AVVideoCompressionPropertiesKey: [AVVideoAverageBitRateKey: 3_000_000, AVVideoMaxKeyFrameIntervalKey: 10]
])
let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: [
    kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32ARGB,
    kCVPixelBufferWidthKey as String: width, kCVPixelBufferHeightKey as String: height,
    kCVPixelBufferCGImageCompatibilityKey as String: true,
    kCVPixelBufferCGBitmapContextCompatibilityKey as String: true
])
try require(writer.canAdd(input), "Cannot add video track")
writer.add(input)
try require(writer.startWriting(), "Video writer start failed")
writer.startSession(atSourceTime: .zero)
var frame = 0
var position = 0.0
var captions = "WEBVTT\n\n"
func stamp(_ seconds: Double) -> String {
    let ms = Int(seconds * 1000)
    return String(format: "%02d:%02d:%02d.%03d", ms / 3_600_000, (ms / 60_000) % 60, (ms / 1000) % 60, ms % 1000)
}
for (index, scene) in scenes.enumerated() {
    let imageURL = root.appendingPathComponent(scene.image).standardizedFileURL
    try require(imageURL.path.hasPrefix(root.path + "/docs/evidence/"), "Only local evidence screenshots are allowed")
    guard let image = NSImage(contentsOf: imageURL), let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        throw RenderError(message: "Cannot read screenshot \(scene.image)")
    }
    var buffer: CVPixelBuffer?
    let status = CVPixelBufferCreate(kCFAllocatorDefault, width, height, kCVPixelFormatType_32ARGB, nil, &buffer)
    try require(status == kCVReturnSuccess && buffer != nil, "Cannot allocate frame")
    let pixel = buffer!
    CVPixelBufferLockBaseAddress(pixel, [])
    guard let context = CGContext(data: CVPixelBufferGetBaseAddress(pixel), width: width, height: height,
                                  bitsPerComponent: 8, bytesPerRow: CVPixelBufferGetBytesPerRow(pixel),
                                  space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.noneSkipFirst.rawValue) else {
        throw RenderError(message: "Cannot draw frame")
    }
    context.setFillColor(CGColor(red: 0.035, green: 0.065, blue: 0.09, alpha: 1))
    context.fill(CGRect(x: 0, y: 0, width: width, height: height))
    let scale = min(1820.0 / Double(cg.width), 835.0 / Double(cg.height))
    let w = Double(cg.width) * scale, h = Double(cg.height) * scale
    context.draw(cg, in: CGRect(x: (1920 - w) / 2, y: 150 + (835 - h) / 2, width: w, height: h))
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: false)
    let paragraph = NSMutableParagraphStyle()
    paragraph.alignment = .center
    (scene.title as NSString).draw(in: NSRect(x: 60, y: 1005, width: 1800, height: 50), withAttributes: [
        .font: NSFont.systemFont(ofSize: 32, weight: .bold), .foregroundColor: NSColor(calibratedRed: 0.6, green: 0.94, blue: 0.78, alpha: 1), .paragraphStyle: paragraph
    ])
    (scene.caption as NSString).draw(in: NSRect(x: 100, y: 62, width: 1720, height: 78), withAttributes: [
        .font: NSFont.systemFont(ofSize: 25, weight: .medium), .foregroundColor: NSColor.white, .paragraphStyle: paragraph
    ])
    ("EDITED ACTUAL-SCREEN WALKTHROUGH | SYNTHETIC DATA | SYSTEM VOICE | \(index + 1)/\(scenes.count)" as NSString).draw(in: NSRect(x: 70, y: 18, width: 1780, height: 26), withAttributes: [
        .font: NSFont.systemFont(ofSize: 15), .foregroundColor: NSColor.lightGray, .paragraphStyle: paragraph
    ])
    NSGraphicsContext.restoreGraphicsState()
    CVPixelBufferUnlockBaseAddress(pixel, [])
    for _ in 0..<Int(durations[index] * Double(fps)) {
        let deadline = Date().addingTimeInterval(30)
        while !input.isReadyForMoreMediaData && writer.status == .writing && Date() < deadline { Thread.sleep(forTimeInterval: 0.01) }
        try require(input.isReadyForMoreMediaData, "Video encoder stalled")
        try require(adaptor.append(pixel, withPresentationTime: CMTime(value: Int64(frame), timescale: Int32(fps))), "Video frame append failed")
        frame += 1
    }
    captions += "\(index + 1)\n\(stamp(position)) --> \(stamp(position + durations[index]))\n\(scene.narration)\n\n"
    position += durations[index]
}
input.markAsFinished()
writer.endSession(atSourceTime: CMTime(seconds: total, preferredTimescale: 600))
await writer.finishWriting()
try require(writer.status == .completed, "Video writing did not complete")
let composition = AVMutableComposition()
let videoTrack = composition.addMutableTrack(withMediaType: .video, preferredTrackID: kCMPersistentTrackID_Invalid)!
let source = AVURLAsset(url: silent)
let sourceTrack = try await source.loadTracks(withMediaType: .video).first!
try videoTrack.insertTimeRange(CMTimeRange(start: .zero, duration: CMTime(seconds: total, preferredTimescale: 600)), of: sourceTrack, at: .zero)
let audioTrack = composition.addMutableTrack(withMediaType: .audio, preferredTrackID: kCMPersistentTrackID_Invalid)!
position = 0
for (index, url) in audioURLs.enumerated() {
    let asset = AVURLAsset(url: url)
    let track = try await asset.loadTracks(withMediaType: .audio).first!
    let duration = try await asset.load(.duration)
    try audioTrack.insertTimeRange(CMTimeRange(start: .zero, duration: duration), of: track, at: CMTime(seconds: position, preferredTimescale: 600))
    position += durations[index]
}
let final = output.appendingPathComponent("OwnStack-demo.mp4")
guard let exporter = AVAssetExportSession(asset: composition, presetName: AVAssetExportPresetHighestQuality) else { throw RenderError(message: "Cannot export final video") }
try await exporter.export(to: final, as: .mp4)
try captions.write(to: output.appendingPathComponent("OwnStack-demo.vtt"), atomically: true, encoding: .utf8)
let finalAsset = AVURLAsset(url: final)
let finalDuration = try await finalAsset.load(.duration).seconds
let tracks = try await finalAsset.load(.tracks)
let generator = AVAssetImageGenerator(asset: finalAsset)
generator.appliesPreferredTrackTransform = true
for (index, seconds) in [5.0, total / 2, total - 5].enumerated() {
    let result = try await generator.image(at: CMTime(seconds: seconds, preferredTimescale: 600))
    let bitmap = NSBitmapImageRep(cgImage: result.image)
    let png = bitmap.representation(using: .png, properties: [:])!
    try png.write(to: output.appendingPathComponent("preview-\(index + 1).png"))
}
let report: [String: Any] = ["file": final.path, "duration_seconds": finalDuration,
                           "video_tracks": tracks.filter { $0.mediaType == .video }.count,
                           "audio_tracks": tracks.filter { $0.mediaType == .audio }.count,
                           "scenes": scenes.count, "inference_calls": 0, "public_youtube_url": NSNull(),
                           "format": "Edited actual-screen still walkthrough, not continuous screen capture; offline system voice"]
let reportData = try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
try reportData.write(to: output.appendingPathComponent("render-report.json"))
print(String(data: reportData, encoding: .utf8)!)
}

do { try await render() }
catch { fputs("Demo render failed: \(error)\n", stderr); exit(1) }
