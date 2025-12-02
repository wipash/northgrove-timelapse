import sys
from timelapse import TimelapseProcessor


def run_daily_process():
    """
    Process daily images and create daily/weekly videos.
    """
    print("Starting daily timelapse processing...")
    processor = TimelapseProcessor()
    processor.process(days_limit=3, upload_all_weeks=False)
    print("Daily timelapse processing finished successfully.")


def run_full_build():
    """
    Build full timelapse from weekly videos only.
    """
    print("Starting full timelapse build...")
    processor = TimelapseProcessor()
    processor.build_full_only()
    print("Full timelapse build finished successfully.")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "daily"

    try:
        if mode == "full":
            run_full_build()
        else:
            run_daily_process()
    except Exception as e:
        print(f"An error occurred during processing: {e}")
        raise


if __name__ == '__main__':
    main()
