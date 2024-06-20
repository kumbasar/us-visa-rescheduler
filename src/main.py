import json
import random
import time
from datetime import datetime
from typing import Union

import requests
from loguru import logger
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait as Wait


from src.constants import COOLDOWN_TIME, EXCEPTION_TIME, RETRY_TIME, STEP_TIME
from src.utils import get_driver, load_config

config = load_config('src/config.ini')
USERNAME = config['USVISA']['USERNAME']
PASSWORD = config['USVISA']['PASSWORD']
SCHEDULE_ID = config['USVISA']['SCHEDULE_ID']
MY_SCHEDULE_DATE = config['USVISA']['MY_SCHEDULE_DATE']
my_date = datetime.strptime(MY_SCHEDULE_DATE, "%Y-%m-%d")
COUNTRY_CODE = config['USVISA']['COUNTRY_CODE']
LOCAL_USE = config['CHROMEDRIVER'].getboolean('LOCAL_USE')
HUB_ADDRESS = config['CHROMEDRIVER']['HUB_ADDRESS']
FACILITY_ID = config['USVISA']['FACILITY_ID']
DATE_URL = (f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/{SCHEDULE_ID}/appointment/days/{FACILITY_ID}."
            f"json?appointments[expedite]=false")
TIME_URL = (f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/{SCHEDULE_ID}/appointment/times/{FACILITY_ID}."
            f"json?date=%s&appointments[expedite]=false")
APPOINTMENT_URL = f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/{SCHEDULE_ID}/appointment"
MAX_DATE_COUNT = 1

driver = get_driver(local_use=LOCAL_USE, hub_address=HUB_ADDRESS)


def interceptor(request):
    request.headers['Accept'] = 'application/json, text/javascript, */*; q=0.01'
    request.headers['X-Requested-With'] = 'XMLHttpRequest'


driver.request_interceptor = interceptor


def login():
    """
    Login to the US Visa appointment system.
    """
    # Open the Appointments service page for the country
    driver.get(f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv")
    time.sleep(STEP_TIME)

    # Click on Continue application
    a = driver.find_element(By.XPATH, '//a[@class="down-arrow bounce"]')
    a.click()
    time.sleep(STEP_TIME)

    logger.info("Login start...")
    href = driver.find_element(
        By.XPATH, '//*[@id="header"]/nav/div/div/div[2]/div[1]/ul/li[3]/a')
    href.click()
    time.sleep(STEP_TIME)
    Wait(driver, 60).until(ec.presence_of_element_located((By.NAME, "commit")))

    logger.info("Click bounce...")
    a = driver.find_element(By.XPATH, '//a[@class="down-arrow bounce"]')
    a.click()
    time.sleep(STEP_TIME)

    # Fill the form
    logger.info("Input email...")
    user = driver.find_element(By.ID, 'user_email')
    user.send_keys(USERNAME)
    time.sleep(random.randint(1, 3))

    logger.info("Input password")
    pw = driver.find_element(By.ID, 'user_password')
    pw.send_keys(PASSWORD)
    time.sleep(random.randint(1, 3))

    logger.info("Click privacy...")
    box = driver.find_element(By.CLASS_NAME, 'icheckbox')
    box .click()
    time.sleep(random.randint(1, 3))

    logger.info("Commit...")
    btn = driver.find_element(By.NAME, 'commit')
    btn.click()
    time.sleep(random.randint(1, 3))

    # FIXME: This is not working for now to check if login is successful
    # Wait(driver, 60).until(
    #     EC.presence_of_element_located((By.XPATH, REGEX_CONTINUE))
    # )
    logger.info("Login successful!")


def get_available_dates():
    """
    Get the date of the next available appointments.
    """
    driver.get(DATE_URL)

    if not is_logged_in():
        login()
        return get_available_dates()
    else:
        content = driver.find_element(By.TAG_NAME, 'pre').text
        date = json.loads(content)
        logger.info(date)
        return date


def get_valid_date(dates: list) -> Union[str, None]:
    """
    Get the first valid date from the list of available dates.
    A valid date is a date that is earlier than MY_SCHEDULE_DATE.

    :param dates: List of available dates
    """

    def is_earlier():
        global earliest_date

        new_date = datetime.strptime(date, "%Y-%m-%d")

        if earliest_date > new_date:
            earliest_date = new_date
            logger.info(f"Found new earliest date: {earliest_date}")

        return my_date > new_date

    logger.info(f"Checking for a date earlier than {MY_SCHEDULE_DATE}...")

    for d in dates:
        date = d.get('date')

        # Check if date is earlier than my schedule date
        if not is_earlier():
            logger.info(f"{date} is not earlier. Earliest: {earliest_date}")
            continue

        return date


def get_time(date):
    """
    Get the time of the next available appointments.

    :param date: Available date to get slot
    :return: Time of the next available appointment.
    """
    time_url = TIME_URL % date
    driver.get(time_url)
    content = driver.find_element(By.TAG_NAME, 'pre').text
    data = json.loads(content)
    time_slot = data.get("available_times")[-1]
    logger.info(f"Got time successfully! {date} {time_slot}")
    return time_slot


def reschedule(date: str) -> bool:
    """
    Reschedule the appointment.

    :param date: Available date to reschedule
    :return: The response of the rescheduling request.
    """
    logger.info(f"Starting Reschedule ({date})")
    time_slot = get_time(date)
    driver.get(APPOINTMENT_URL)

    data = {
        "utf8": driver.find_element(by=By.NAME, value='utf8').get_attribute('value'),
        "authenticity_token": driver.find_element(by=By.NAME, value='authenticity_token').get_attribute('value'),
        "confirmed_limit_message": driver.find_element(
            by=By.NAME, value='confirmed_limit_message'
        ).get_attribute('value'),
        "use_consulate_appointment_capacity": driver.find_element(
            by=By.NAME, value='use_consulate_appointment_capacity'
        ).get_attribute('value'),
        "appointments[consulate_appointment][facility_id]": FACILITY_ID,
        "appointments[consulate_appointment][date]": date,
        "appointments[consulate_appointment][time]": time_slot,
    }

    headers = {
        "User-Agent": driver.execute_script("return navigator.userAgent;"),
        "Referer": APPOINTMENT_URL,
        "Cookie": "_yatri_session=" + driver.get_cookie("_yatri_session")["value"]
    }

    r = requests.post(APPOINTMENT_URL, headers=headers, data=data)
    if r.text.find('Successfully Scheduled') != -1:
        logger.info(f"Rescheduled Successfully! {date} {time_slot}")
        return True

    logger.info(f"Reschedule Failed. {date} {time_slot}")
    return False


def is_logged_in():
    content = driver.page_source
    return content.find('error') == -1


def search_for_available_date():
    """
    Search for available appointment date and reschedule if found.

    :return: True if reschedule successfully, otherwise call itself again.
    """
    logger.info("Searching for available date...")
    time.sleep(random.randint(1, 3))
    dates = get_available_dates()[:MAX_DATE_COUNT]
    if not dates:
        sleep = random.randint(5, RETRY_TIME)
        logger.info(f"No available date, retrying in {sleep} seconds...")
        time.sleep(sleep)
        return search_for_available_date()

    date = get_valid_date(dates)
    if date:
        logger.info(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! Found early date: {date}")
        if reschedule(date):
            logger.info("Reschedule successfully!")
            return True
        else:
            logger.info(f"Reschedule failed, retrying in {COOLDOWN_TIME} seconds...")
            time.sleep(COOLDOWN_TIME)

    sleep = random.randint(10, RETRY_TIME)
    logger.info(f"No earlier date, retrying in {sleep} seconds...")
    time.sleep(sleep)
    return search_for_available_date()


if __name__ == "__main__":
    logger.add("visa_{time}.log")

    login()

    earliest_date = datetime.strptime('2030-12-30', "%Y-%m-%d")

    while True:
        try:
            if search_for_available_date():
                break
        except Exception as e:
            logger.error(e)
            logger.error(f"Exception occurred, retrying after {EXCEPTION_TIME} seconds...")
            time.sleep(EXCEPTION_TIME)
