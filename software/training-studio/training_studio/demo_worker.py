"""Portable cooperative demo child. Its outputs are never robot policies."""
import argparse
import json
import queue
import sys
import threading
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, required=True)
    parser.add_argument("--save-interval", type=int, required=True)
    parser.add_argument("--interval", type=float, default=0.45)
    parser.add_argument("--start-iteration", type=int, default=0)
    args = parser.parse_args()
    commands = queue.Queue()

    def reader():
        for line in sys.stdin:
            commands.put(line.strip())
        commands.put("stop")

    def emit(event, **data):
        print(json.dumps({"event": event, **data}), flush=True)

    threading.Thread(target=reader, daemon=True).start()
    emit("ready", message="DEMO：流程演示，曲线为合成数据，检查点不是模型。")
    paused = False
    iteration = args.start_iteration
    # The count represents additional iterations, as rsl_rl runner.learn does.
    target = iteration + args.iterations
    while iteration < target:
        try:
            command = commands.get(timeout=None if paused else args.interval)
            if command == "stop":
                emit("stopped")
                return
            if command == "pause":
                paused = True
                emit("paused")
            elif command == "resume":
                paused = False
                emit("resumed")
        except queue.Empty:
            iteration += 1
            emit("metric", iteration=iteration, reward=round(-3 + iteration * 0.38, 3),
                 episode_length=min(1000, 12 + iteration * 3), fps=1280.0)
            if iteration % args.save_interval == 0 or iteration == target:
                emit("checkpoint", iteration=iteration)
    emit("completed")


if __name__ == "__main__":
    main()
