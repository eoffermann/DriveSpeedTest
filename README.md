# README
================

## Introduction
---------------

This script is designed to perform drive speed tests on a selected drive. The tests include sequential read/write and random read/write operations. The script uses the Gradio library to create an interface for selecting the drive and displaying the test results.

## Installation and Setup
-------------------------

To install the script, follow these steps:

### Step 1: Create a Conda Environment

Create a new Conda environment using the following command:
```bash
conda create --name drive_speed_test python=3.9
```
Replace `drive_speed_test` with your desired environment name.

### Step 2: Activate the Environment

Activate the newly created environment using the following command:
```bash
conda activate drive_speed_test
```

### Step 3: Install Requirements

Install the required packages from the `requirements.txt` file using pip:
```bash
pip install -r requirements.txt
```
The `requirements.txt` file should contain the following lines:
```
gradio
psutil
```
You can add any additional dependencies as needed.

### Step 4: Verify Installation

Verify that the installation was successful by running the script. You should see the Gradio interface with a dropdown menu of available drives.

## Running the Script
---------------------

To run the script, follow these steps:

1. Navigate to the directory containing the script using your command line or terminal.
2. Run the script using Python:
```bash
python drive_speed_test.py
```
Replace `drive_speed_test.py` with the actual name of your script file.

3. Open a web browser and navigate to `http://localhost:7860/`. You should see the Gradio interface with a dropdown menu of available drives.
4. Select a drive from the dropdown menu and click the "Submit" button to start the tests.

## What to Expect
-----------------

The script will perform the following tests:

* Sequential Write Test: Writes a large file to the selected drive and measures the time it takes to complete.
* Sequential Read Test: Reads the same file and measures the time it takes to complete.
* Random Write Test: Writes random data to the selected drive in small blocks and measures the time it takes to complete.
* Random Read Test: Reads the same data and measures the time it takes to complete.

The results of the tests will be displayed in the output text area, including:

* Sequential Write Speed (MB/s)
* Sequential Read Speed (MB/s)
* Random Write Speed (MB/s)
* Random Read Speed (MB/s)

## Troubleshooting
------------------

If you encounter any issues while running the script, check the following:

* Make sure you have administrative privileges to run the script.
* Verify that the selected drive has enough free space to perform the tests.
* Check for any errors in the output text area or the command line.

## Requirements
------------

The script requires the following dependencies:

* Python 3.9+
* Gradio library (`pip install gradio`)
* Psutil library (`pip install psutil`)

## Known Limitations
-------------------

The script has the following limitations:

* The tests may take some time to complete depending on the size of the test file and the speed of the drive.
* The script is designed for testing purposes only and should not be used in production environments without proper modifications and error handling.

## Future Development
---------------------

Future development plans include:

* Adding support for multiple drives at once
* Improving error handling and logging
* Adding additional tests for other types of storage devices