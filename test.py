import psutil
import gradio as gr
import time
import os
import random
import string

def get_available_drives():
    """Return a list of available drives."""
    return [f"{disk.device[0].upper()}" for disk in psutil.disk_partitions()]

def generate_random_string(length):
    """Generate a random string of the specified length."""
    letters = string.ascii_lowercase
    return ''.join(random.choice(letters) for _ in range(length))

def test_drive(drive_letter, test_size=1024*1024*100):  # 100MB test size
    """
    Test the drive speed by performing sequential read/write and random read/write operations.

    Args:
        drive_letter (str): The letter of the drive to test.
        test_size (int): The size of the test file in bytes. Defaults to 100MB.

    Returns:
        dict: A dictionary containing the results of the tests.
    """
    results = {}
    
    # Create a temporary test file
    temp_file = f"{drive_letter}:\\temp_test_file.txt"
    
    # Sequential Write Test
    start_time = time.time()
    with open(temp_file, 'wb') as f:
        f.write(bytearray(test_size))
    end_time = time.time()
    results["sequential_write_speed"] = (test_size / (end_time - start_time)) / (1024*1024)  # MB/s
    
    # Sequential Read Test
    start_time = time.time()
    with open(temp_file, 'rb') as f:
        f.read(test_size)
    end_time = time.time()
    results["sequential_read_speed"] = (test_size / (end_time - start_time)) / (1024*1024)  # MB/s
    
    # Random Write Test
    random_data = bytearray([random.randint(0, 255) for _ in range(test_size)])
    start_time = time.time()
    with open(temp_file, 'wb') as f:
        for i in range(0, test_size, 4096):
            f.seek(i)
            f.write(random_data[i:i+4096])
    end_time = time.time()
    results["random_write_speed"] = (test_size / (end_time - start_time)) / (1024*1024)  # MB/s
    
    # Random Read Test
    start_time = time.time()
    with open(temp_file, 'rb') as f:
        for i in range(0, test_size, 4096):
            f.seek(i)
            f.read(4096)
    end_time = time.time()
    results["random_read_speed"] = (test_size / (end_time - start_time)) / (1024*1024)  # MB/s
    
    # Remove the temporary test file
    os.remove(temp_file)
    
    return results

def main(drive_letter):
    """Perform drive speed tests and display the results."""
    available_drives = get_available_drives()
    if drive_letter.upper() not in available_drives:
        return f"Error: Drive {drive_letter} is not available."
    
    try:
        results = test_drive(drive_letter)
        output = f"Drive Speed Test Results for {drive_letter}:\n"
        output += f"Sequential Write Speed: {results['sequential_write_speed']:.2f} MB/s\n"
        output += f"Sequential Read Speed: {results['sequential_read_speed']:.2f} MB/s\n"
        output += f"Random Write Speed: {results['random_write_speed']:.2f} MB/s\n"
        output += f"Random Read Speed: {results['random_read_speed']:.2f} MB/s"
        return output
    except Exception as e:
        return f"Error: {str(e)}"

demo = gr.Interface(
    fn=main,
    inputs=gr.Dropdown(choices=get_available_drives()),
    outputs="text",
    title="Drive Speed Test",
    description="Select a drive to test its speed.",
)

if __name__ == "__main__":
    demo.launch()