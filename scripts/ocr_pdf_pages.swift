import AppKit
import Foundation
import PDFKit
import Vision

guard CommandLine.arguments.count == 5,
      let firstPage = Int(CommandLine.arguments[2]),
      let lastPage = Int(CommandLine.arguments[3]) else {
    FileHandle.standardError.write(Data("usage: ocr_pdf_pages.swift input.pdf first_page last_page output.txt\n".utf8))
    exit(2)
}

let input = URL(fileURLWithPath: CommandLine.arguments[1])
let output = URL(fileURLWithPath: CommandLine.arguments[4])
guard let document = PDFDocument(url: input) else {
    FileHandle.standardError.write(Data("cannot open PDF\n".utf8))
    exit(1)
}
guard firstPage >= 1, lastPage >= firstPage, lastPage <= document.pageCount else {
    FileHandle.standardError.write(Data("page range out of bounds: document has \(document.pageCount) pages\n".utf8))
    exit(2)
}

var result = ""
for pageNumber in firstPage...lastPage {
    autoreleasepool {
        guard let page = document.page(at: pageNumber - 1) else { return }
        let bounds = page.bounds(for: .mediaBox)
        let scale: CGFloat = 3.0
        let width = Int(bounds.width * scale)
        let height = Int(bounds.height * scale)
        guard let context = CGContext(
            data: nil, width: width, height: height, bitsPerComponent: 8,
            bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        ) else { return }
        context.setFillColor(NSColor.white.cgColor)
        context.fill(CGRect(x: 0, y: 0, width: width, height: height))
        context.scaleBy(x: scale, y: scale)
        page.draw(with: .mediaBox, to: context)
        guard let image = context.makeImage() else { return }

        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.recognitionLanguages = ["zh-Hans", "en-US"]
        request.usesLanguageCorrection = true
        do {
            try VNImageRequestHandler(cgImage: image).perform([request])
            let observations = request.results ?? []
            let lines = observations.compactMap { $0.topCandidates(1).first?.string }
            result += "\n=== PAGE \(pageNumber) ===\n" + lines.joined(separator: "\n") + "\n"
            print("ocr page \(pageNumber): \(lines.count) lines")
        } catch {
            FileHandle.standardError.write(Data("OCR failed on page \(pageNumber): \(error)\n".utf8))
        }
    }
}
try result.write(to: output, atomically: true, encoding: .utf8)
print("output=\(output.path)")
