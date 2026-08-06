import Foundation
import PDFKit

guard CommandLine.arguments.count == 3 || (CommandLine.arguments.count == 4 && CommandLine.arguments[3] == "--force") else {
    FileHandle.standardError.write(Data("usage: extract_pdf_batch.swift input-root output-root [--force]\n".utf8))
    exit(2)
}

let manager = FileManager.default
let inputRoot = URL(fileURLWithPath: CommandLine.arguments[1]).resolvingSymlinksInPath().standardizedFileURL
let outputRoot = URL(fileURLWithPath: CommandLine.arguments[2]).resolvingSymlinksInPath().standardizedFileURL
try manager.createDirectory(at: outputRoot, withIntermediateDirectories: true)
guard let enumerator = manager.enumerator(
    at: inputRoot,
    includingPropertiesForKeys: [.isRegularFileKey],
    options: [.skipsHiddenFiles]
) else { exit(1) }

func relativePath(of input: URL, to root: URL) -> String? {
    let inputPath = input.resolvingSymlinksInPath().standardizedFileURL.path
    let rootPath = root.path
    let prefix = rootPath.hasSuffix("/") ? rootPath : rootPath + "/"
    guard inputPath.hasPrefix(prefix) else { return nil }
    return String(inputPath.dropFirst(prefix.count))
}

var succeeded = 0
var failed = 0
var skipped = 0
let force = CommandLine.arguments.count == 4
for case let input as URL in enumerator where input.pathExtension.lowercased() == "pdf" {
    guard let relative = relativePath(of: input, to: inputRoot), !relative.isEmpty else {
        failed += 1
        print("failed \(input.path): not under input root \(inputRoot.path)")
        continue
    }
    let output = outputRoot.appendingPathComponent(relative).deletingPathExtension().appendingPathExtension("txt")
    if !force && manager.fileExists(atPath: output.path) {
        skipped += 1
        continue
    }
    do {
        guard let document = PDFDocument(url: input) else { throw NSError(domain: "PDFKit", code: 1) }
        var text = ""
        for pageIndex in 0..<document.pageCount {
            text += "\n=== PAGE \(pageIndex + 1) ===\n"
            text += document.page(at: pageIndex)?.string ?? ""
            text += "\n"
        }
        try manager.createDirectory(at: output.deletingLastPathComponent(), withIntermediateDirectories: true)
        try text.write(to: output, atomically: true, encoding: .utf8)
        succeeded += 1
        print("ok \(relative) pages=\(document.pageCount)")
    } catch {
        failed += 1
        print("failed \(relative): \(error)")
    }
}
print("completed succeeded=\(succeeded) skipped=\(skipped) failed=\(failed)")
if failed > 0 { exit(2) }
