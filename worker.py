from timelapse import TimelapseProcessor

def run_automated_process():
    """
    This is the entry point for the automated serverless process.
    It creates the daily and weekly videos, but not the full timelapse.
    """
    print("Starting automated timelapse processing...")
    try:
        # In the automated environment, uploads should always be enabled.
        processor = TimelapseProcessor(upload_enabled=True)

        # We process the last 3 days to catch any images that might have been
        # added late to the previous day's folder. The `create_daily_video`
        # function is smart enough to skip days that are already processed and
        # haven't changed.
        processor.process(
            days_limit=3,
            upload_all_weeks=False,
            build_full=False
        )
        print("Automated timelapse processing finished successfully.")
    except Exception as e:
        print(f"An error occurred during automated processing: {e}")
        # In a real-world scenario, you might want to send a notification here.
        raise

if __name__ == '__main__':
    run_automated_process()
