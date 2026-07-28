import AppKit
import Foundation
import Vision

func emit(_ value: Any) {
    let data = try! JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
    print(String(data: data, encoding: .utf8)!)
}

func bodyPoints(_ observation: VNHumanBodyPoseObservation) -> [[String: Any]] {
    guard let points = try? observation.recognizedPoints(.all) else { return [] }
    return points.map { name, point in
        [
            "name": name.rawValue,
            "x": Double(point.location.x),
            "y": Double(point.location.y),
            "confidence": Double(point.confidence),
        ]
    }
}

guard CommandLine.arguments.count == 2 else {
    emit(["available": false, "reason": "manifest_missing"])
    exit(0)
}

do {
    let data = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
    guard let manifest = try JSONSerialization.jsonObject(with: data) as? [[String: Any]] else {
        emit(["available": false, "reason": "manifest_invalid"])
        exit(0)
    }
    var frames: [[String: Any]] = []
    for item in manifest {
        let identifier = item["identifier"] as? Int ?? -1
        guard let path = item["path"] as? String,
              let image = NSImage(contentsOfFile: path),
              let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
            frames.append(["identifier": identifier, "available": false, "reason": "decode_failed"])
            continue
        }
        let faces = VNDetectFaceRectanglesRequest()
        let bodies = VNDetectHumanBodyPoseRequest()
        let hands = VNDetectHumanHandPoseRequest()
        hands.maximumHandCount = 2
        do {
            try VNImageRequestHandler(cgImage: cgImage, options: [:]).perform([faces, bodies, hands])
            let faceRows = (faces.results ?? []).map { observation in
                [
                    "x": Double(observation.boundingBox.minX),
                    "y": Double(observation.boundingBox.minY),
                    "width": Double(observation.boundingBox.width),
                    "height": Double(observation.boundingBox.height),
                    "confidence": Double(observation.confidence),
                ]
            }
            let bodyRows = (bodies.results ?? []).map { ["points": bodyPoints($0)] }
            frames.append([
                "identifier": identifier,
                "available": true,
                "faces": faceRows,
                "bodies": bodyRows,
                "handCount": (hands.results ?? []).count,
            ])
        } catch {
            frames.append([
                "identifier": identifier,
                "available": false,
                "reason": "vision_request_failed",
                "error": error.localizedDescription,
            ])
        }
    }
    emit([
        "available": true,
        "provider": "apple_vision",
        "requests": [
            "VNDetectFaceRectanglesRequest",
            "VNDetectHumanBodyPoseRequest",
            "VNDetectHumanHandPoseRequest",
        ],
        "frames": frames,
    ])
} catch {
    emit(["available": false, "reason": "vision_runtime_failed", "error": error.localizedDescription])
}
