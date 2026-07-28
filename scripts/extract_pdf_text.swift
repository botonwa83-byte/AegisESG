import Foundation
import PDFKit

guard CommandLine.arguments.count == 3 else {
    FileHandle.standardError.write(Data("usage: extract_pdf_text.swift input.pdf output.txt\n".utf8))
    exit(2)
}

let input = URL(fileURLWithPath: CommandLine.arguments[1])
let output = URL(fileURLWithPath: CommandLine.arguments[2])
guard let document = PDFDocument(url: input) else {
    FileHandle.standardError.write(Data("cannot open PDF\n".utf8))
    exit(1)
}

var text = ""
for pageIndex in 0..<document.pageCount {
    text += "\n=== PAGE \(pageIndex + 1) ===\n"
    text += document.page(at: pageIndex)?.string ?? ""
    text += "\n"
}
try text.write(to: output, atomically: true, encoding: .utf8)
print("pages=\(document.pageCount) output=\(output.path)")
