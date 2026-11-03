"""Create a tiny deterministic TFLite model for the Android inference smoke test.

The model is synthetic: it predicts from the mean red and green channels and
is not a trained product model or a measure of recognition accuracy.
"""
from pathlib import Path

import tensorflow as tf


@tf.function(input_signature=[tf.TensorSpec([1, 4, 4, 3], tf.float32)])
def fixture_model(image):
    channels = tf.reduce_mean(image, axis=[1, 2])
    return tf.nn.softmax(channels[:, :2], axis=-1)


def main():
    converter = tf.lite.TFLiteConverter.from_concrete_functions(
        [fixture_model.get_concrete_function()])
    model = converter.convert()
    target = (Path(__file__).resolve().parents[2] / "android" / "app" / "src"
              / "androidTest" / "assets" / "pvl-test.tflite")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(model)
    print(f"Synthetic Android test fixture: {target} ({len(model)} bytes)")


if __name__ == "__main__":
    main()
