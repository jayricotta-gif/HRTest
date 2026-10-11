from heartrate_monitor import HeartRateMonitor
from gpiozero import Button, LED
import time
import argparse
import io          # Added for in-memory handling
import subprocess  # Added for running rclone

# Setting GPIO pins
BUTTON_PIN = 26
SAMPLE_INTERVAL = 0.5
MIN_SAMPLES = 5    
RED = LED(22)
YELLOW = LED(27)
GREEN = LED(17)     

# Communicates between scripts
parser = argparse.ArgumentParser(description="Read BPM and SpO2 from MAX30102")
parser.add_argument("-d", "--duration", type=int, default=10,
                    help="seconds to average over when button is pressed, default 10")
args = parser.parse_args()

# Function to upload directly to Google Drive without saving to SD card
def send_to_google_drive(date_str, time_str, bpm, spo2):
    """Downloads the current log into RAM, appends the new data, and pushes it back."""
    remote_path = 'gdrive:logs/heartrate_log.csv'
    new_line = f"{date_str},{time_str},{spo2:.0f}%,{bpm:.0f}\n"
    
    # 1. Start with standard headers in memory in case the file doesn't exist yet
    current_content = "Date,Time,Avg_SpO2,Avg_BPM\n"
    
    try:
        # 2. Try to download the existing file content straight into RAM
        # stdout=subprocess.PIPE grabs the file contents directly without an SD card file
        result = subprocess.run(['rclone', 'cat', remote_path], stdout=subprocess.PIPE, text=True, stderr=subprocess.DEVNULL)
        
        if result.returncode == 0 and result.stdout.strip():
            current_content = result.stdout
            # Ensure the existing file ends with a clean newline before adding the row
            if not current_content.endswith('\n'):
                current_content += '\n'
    except Exception:
        # If the file doesn't exist yet on Google Drive, it safely passes and creates a new one
        print("Log file not found on drive. Creating a new one...")

    # 3. Append the new reading row to the existing text in RAM
    updated_content = current_content + new_line
    
    # 4. Stream the whole bundle back up to Google Drive (Zero local storage used)
    try:
        process = subprocess.Popen(
            ['rclone', 'rcat', remote_path], 
            stdin=subprocess.PIPE, 
            text=True
        )
        process.communicate(input=updated_content)
        print("Data successfully updated on Google Drive!")
    except Exception as e:
        print(f"Failed to send data to Google Drive: {e}")

# Function that contains the math for calculating the average
def measure_average(hrm, duration):
    """Sample the sensor for `duration` seconds and return (avg_bpm, avg_spo2)."""
    bpm_vals, spo2_vals = [], []
    end_time = time.time() + duration

    while time.time() < end_time:
        if hrm.bpm > 0:        # 0 means no finger / no valid reading yet
            bpm_vals.append(hrm.bpm)
        if hrm.spo2 > 0:
            spo2_vals.append(hrm.spo2)
        time.sleep(SAMPLE_INTERVAL)

    if len(bpm_vals) < MIN_SAMPLES or len(spo2_vals) < MIN_SAMPLES:
        return None
    return sum(bpm_vals) / len(bpm_vals), sum(spo2_vals) / len(spo2_vals)


button = Button(BUTTON_PIN, pull_up=True)

print("sensor starting...")
hrm = HeartRateMonitor(print_raw=False, print_result=False)   # no constant printing
hrm.start_sensor()


# Runs the sensor and processes data
try:
    while True:
        print("Place your finger on the sensor, then press the button...")
        button.wait_for_press()
        YELLOW.on()
        print(f"Measuring for {args.duration}s, keep still...")
        result = measure_average(hrm, args.duration)
        YELLOW.off()
        if result is None:
            print("Not enough valid readings. Check finger placement and try again.\n")
        else:
            avg_bpm, avg_spo2 = result
            print(f"Average BPM: {avg_bpm:.0f}, SpO2: {avg_spo2:.0f}%\n")
            
            # Get current Date and Time right at the moment of calculation
            current_date = time.strftime("%Y-%m-%d")
            current_time = time.strftime("%H:%M:%S")
            
            # Send the metrics directly to your cloud spreadsheet file
            send_to_google_drive(current_date, current_time, avg_bpm, avg_spo2)
            
            # Blink if BPM or SPo2 is unusual
            if avg_bpm >= 100:
                print("Heart Rate is unusually high, please keep an eye on this and if the issue continues consider seeing your doctor")
                for i in range(5):
                    RED.blink()
            if avg_spo2 <= 93:
                print("SPo2 is unusually low, please keep an eye on this and if the issue continues consider seeing your doctor")
                for i in range(5):
                    RED.blink()
                

        button.wait_for_release()
# Ctrl C handling
except KeyboardInterrupt:
    print("keyboard interrupt detected, exiting...")

finally:
    hrm.stop_sensor()
    print("sensor stopped!")