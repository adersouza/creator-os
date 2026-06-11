import Foundation
import Vision
import AppKit

func jsonPrint(_ value: Any) {
    let data = try! JSONSerialization.data(withJSONObject: value, options: [])
    print(String(data: data, encoding: .utf8)!)
}

guard CommandLine.arguments.count >= 2 else {
    jsonPrint([
        "available": false,
        "engine": "apple_vision",
        "error": "Usage: apple-vision-ocr.swift <image-path>",
        "boxes": []
    ])
    exit(1)
}

let imagePath = CommandLine.arguments[1]
guard let image = NSImage(contentsOfFile: imagePath),
      let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    jsonPrint([
        "available": false,
        "engine": "apple_vision",
        "error": "Could not load image",
        "boxes": []
    ])
    exit(1)
}

var boxes: [[String: Any]] = []
let request = VNRecognizeTextRequest { request, error in
    if let error = error {
        jsonPrint([
            "available": false,
            "engine": "apple_vision",
            "error": error.localizedDescription,
            "boxes": []
        ])
        exit(1)
    }

    let observations = request.results as? [VNRecognizedTextObservation] ?? []
    for observation in observations {
        guard let candidate = observation.topCandidates(1).first else { continue }
        let rect = observation.boundingBox
        let width = CGFloat(cgImage.width)
        let height = CGFloat(cgImage.height)
        boxes.append([
            "ocrText": candidate.string,
            "confidence": Int(round(candidate.confidence * 100)),
            "box": [
                "x": Int(round(rect.minX * width)),
                "y": Int(round((1.0 - rect.maxY) * height)),
                "w": Int(round(rect.width * width)),
                "h": Int(round(rect.height * height))
            ],
            "frame": [
                "width": cgImage.width,
                "height": cgImage.height
            ]
        ])
    }
}

request.recognitionLevel = .accurate
request.usesLanguageCorrection = true

do {
    try VNImageRequestHandler(cgImage: cgImage, options: [:]).perform([request])
    jsonPrint([
        "available": true,
        "engine": "apple_vision",
        "engineVersion": "Vision",
        "boxes": boxes
    ])
} catch {
    jsonPrint([
        "available": false,
        "engine": "apple_vision",
        "error": error.localizedDescription,
        "boxes": []
    ])
    exit(1)
}
