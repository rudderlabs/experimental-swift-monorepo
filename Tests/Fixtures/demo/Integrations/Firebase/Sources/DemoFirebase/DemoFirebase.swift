import DemoSDK
import DemoShared
import OrderedCollections

public enum DemoFirebase {
    public static func track(_ names: [String]) -> [DemoEvent] {
        OrderedSet(names.map(DemoNormalizer.normalize)).map {
            DemoEvent(name: $0, destination: "firebase")
        }
    }
}
