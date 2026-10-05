import DemoSDK
import DemoShared

public enum DemoSprig {
    public static func track(_ name: String) -> DemoEvent {
        DemoEvent(name: DemoNormalizer.normalize(name), destination: "sprig")
    }
}
