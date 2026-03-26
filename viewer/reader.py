import os
import capnp
import zstandard as zstd

# 1. Setup paths and load schema
CEREAL_DIR = os.path.abspath('./cereal') 
log_capnp = capnp.load(os.path.join(CEREAL_DIR, 'log.capnp'), imports=[CEREAL_DIR])

def test_rlog_zst(file_path):
    print(f"--- Opening: {file_path} ---")
    dctx = zstd.ZstdDecompressor()
    
    try:
        with open(file_path, 'rb') as f:
            # Decompress the entire stream into a bytes object
            with dctx.stream_reader(f) as reader:
                data = reader.read()
            
            # 2. Iterate through the byte stream manually
            # Using 'flat' parsing: read_multiple_bytes is the magic method 
            # that accepts a raw bytes object without needing a fileno.
            events = log_capnp.Event.read_multiple_bytes(data)
            
            print("Successfully parsed! Sampling messages:")
            for i, event in enumerate(events):
                msg_type = event.which()
                
                # if msg_type == 'carState':
                #     print(f"[{i}] Speed: {event.carState.vEgo:.2f} m/s | Steering: {event.carState.steeringAngleDeg:.1f}°")
                if msg_type == 'errorLogMessage':
                    print(event.errorLogMessage)
                
                # Limit the console output so we don't freeze the terminal
                if i > 2000:
                    print("... (truncated)")
                    break
                    
    except Exception as e:
        print(f"Failed to parse: {e}")

if __name__ == "__main__":
    test_rlog_zst("/mnt/c/Users/bryan/Desktop/qlog.zst")