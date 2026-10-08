import DemoSDK
import DemoShared

public enum DemoSprig {
    public static func track(_ name: String) -> DemoEvent {
        let normalized = DemoNormalizer.normalize(name)
        return DemoEvent(name: normalized.isEmpty ? "unnamed event" : normalized, destination: "sprig")
    }
}
