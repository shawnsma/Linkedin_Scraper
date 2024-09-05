import pandas as pd
import json
import time
import os
import anthropic
import re
from openai import OpenAI
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException, StaleElementReferenceException
from selenium.webdriver.safari.options import Options
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed


#Setting up driver and linkedin login
def setup(un, pw):

    options = Options()
    driver = webdriver.Safari(options=options)
    driver.set_page_load_timeout(60)
    driver.get("https://linkedin.com/uas/login")

    username = driver.find_element(By.ID, "username")
    username.send_keys(un)
    pword = driver.find_element(By.ID, "password")
    pword.send_keys(pw)

    driver.find_element(By.XPATH, "//button[@type='submit']").click()
    return driver


# Utilizing driver and keywords to look over pages of linkedin
def search(driver, keywords, page):
    queued = []
    searchlink = f"https://www.linkedin.com/search/results/people/?keywords={keywords}&origin=SWITCH_SEARCH_VERTICAL&page={page}"
    retry_attempts = 3

    for attempt in range(retry_attempts):
        try:
            driver.get(searchlink)
            start = time.time()
            initialScroll = 0
            finalScroll = 1000
            while True:
                driver.execute_script(f"window.scrollTo({initialScroll}, {finalScroll})")
                initialScroll = finalScroll
                finalScroll += 1000
                end = time.time()
                if round(end - start) > 1:
                    break
            people = WebDriverWait(driver, 1).until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'span.entity-result__title-text')))

            for person in people:
                link = person.find_element(By.CSS_SELECTOR, 'a')
                href = link.get_attribute('href')
                queued.append(href)
            return queued

        except StaleElementReferenceException:
            time.sleep(1)
            person = WebDriverWait(driver, 1).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'span.entity-result__title-text')))
            link = person.find_element(By.CSS_SELECTOR, 'a')
            href = link.get_attribute('href')
            queued.append(href)

        except TimeoutException:
            if attempt < retry_attempts - 1:
                print(f"Timeout occurred. Retrying {attempt + 1}/{retry_attempts}...")
                time.sleep(1)
            else:
                print(f"Failed to load {searchlink} after {retry_attempts} attempts.")
                return []
            

# Getting each individual profile
def get_profile(driver, url):
    retry_attempts = 3
    for attempt in range(retry_attempts):
        try:
            driver.get(url)
            start = time.time()
            initialScroll = 0
            finalScroll = 1000

            while True:
                driver.execute_script(f"window.scrollTo({initialScroll}, {finalScroll})")
                initialScroll = finalScroll
                finalScroll += 1000
                end = time.time()
                if round(end - start) > 1:
                    break

            src = driver.page_source
            soup = BeautifulSoup(src, 'html.parser')
            intro = soup.find('div', {'class': 'mt2 relative'})

            if intro:
                person = {key: [] for key in ['name', 'current job', 'currcompany', 'location', 'about', 'total months worked', 'url']}
                name_loc = intro.find("h1")
                name = name_loc.get_text().strip()
                try:
                    works_at_loc = intro.find("div", {'class': 'text-body-medium break-words'})
                except NoSuchElementException:
                    works_at_loc = ""
                works_at = works_at_loc.get_text().strip()
                
                try:
                    company_element = driver.find_element(By.CSS_SELECTOR, 'button[aria-label^="Current company"]')
                    if company_element:
                        company = company_element.text.strip()
                except NoSuchElementException:
                    company = ""

                try:
                    location_loc = intro.find_all("span", {'class': 'text-body-small inline t-black--light break-words'})
                except NoSuchElementException:
                    location_loc = ""
                location = location_loc[0].get_text().strip() if location_loc else ""

                person['name'].append(name)
                person['current job'].append(works_at)
                person['currcompany'].append(company)
                person['location'].append(location)
                person['url'].append(url)

                about = soup.find("div", {'class': 'display-flex ph5 pv3'})
                if about:
                    about_loc = about.find("div", {'class': 'display-flex full-width'})
                    desc = about_loc.get_text().strip()
                    person['about'].append(desc)
                else:
                    person['about'].append("")

                edu = {key: [] for key in ['school', 'degree', 'dates']}
                schools = driver.find_elements(By.CSS_SELECTOR, 'section:has(#education)>div>ul>li')
                for school in schools:
                    try:
                        schoolscript = school.find_element(By.CSS_SELECTOR, 'div[class="display-flex flex-wrap align-items-center full-height"]').text
                    except NoSuchElementException:
                        schoolscript = ""
                    index = 0
                    for char in schoolscript:
                        index += 1
                        if char == "\n":
                            schoolscript = schoolscript[:index]
                            break
                    edu['school'].append(schoolscript)
                    try:
                        degreescript = school.find_element(By.CSS_SELECTOR, 'span[class="t-14 t-normal"]').text
                    except NoSuchElementException:
                        degreescript = ""
                    index = 0
                    for char in degreescript:
                        index += 1
                        if char == "\n":
                            degreescript = degreescript[:index]
                            break
                    edu['degree'].append(degreescript)
                    try:
                        edu['dates'] += [school.find_element(By.CSS_SELECTOR, 'span[class="pvs-entity__caption-wrapper"]').text]
                    except NoSuchElementException:
                        edu['dates'].append("")
                eduf = pd.DataFrame(edu)

                exp = {key: [] for key in ['job', 'company', 'date', 'description']}
                total_months = 0
                try:
                    see_more = driver.find_element(By.ID, "navigation-index-see-all-experiences")
                    driver.execute_script("arguments[0].scrollIntoView(true);", see_more)
                    time.sleep(1)
                    driver.execute_script("arguments[0].click();", see_more)
                    time.sleep(1)
                    start = time.time()
                    initialScroll = 0
                    finalScroll = 1000

                    while True:
                        driver.execute_script(f"window.scrollTo({initialScroll}, {finalScroll})")
                        initialScroll = finalScroll
                        finalScroll += 1000
                        end = time.time()
                        if round(end - start) > 1:
                            break
                    experience_section = WebDriverWait(driver, 1).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "div.scaffold-finite-scroll__content"))
                    )
                    jobs = experience_section.find_elements(By.CSS_SELECTOR, "li.pvs-list__paged-list-item")

                except NoSuchElementException:
                    jobs = driver.find_elements(By.CSS_SELECTOR, 'section:has(#experience)>div>ul>li')
                    pass

                moved = 1
                for job in jobs:
                    try:
                        jobscript = job.find_element(By.CSS_SELECTOR, 'div[class="display-flex flex-wrap align-items-center full-height"]').text
                    except NoSuchElementException:
                        jobscript = ""
                    index = 0
                    for char in jobscript:
                        index += 1
                        if char == "\n":
                            jobscript = jobscript[:index]
                            break

                    try:
                        new_date = job.find_element(By.CSS_SELECTOR, 'span[class="pvs-entity__caption-wrapper"]').text
                    except NoSuchElementException:
                        new_date = ""

                    try:
                        companyscript = job.find_element(By.CSS_SELECTOR, 'span[class="t-14 t-normal"]')
                        if companyscript:
                            companyscript = companyscript.text
                    except NoSuchElementException:
                        companyscript = ""
                    index = 0
                    for char in companyscript:
                        index += 1
                        if char == "\n":
                            companyscript = companyscript[:index]
                            break

                    try:
                        description = driver.execute_script('return arguments[0].querySelector("ul li ul span[aria-hidden=true]")?.innerText', job)
                    except NoSuchElementException:
                        description = ""

                    indicator = 0

                    if companyscript.startswith("Full-time") and len(companyscript) < 15:
                        indicator = 1

                    if companyscript == "" or indicator == 1:
                        if moved == 0:
                            companyscript = exp['company'][-1]
                        if moved == 1:
                            companyscript = exp['job'][-1]
                            del exp['job'][-1]
                            del exp['date'][-1]
                            del exp['company'][-1]
                            del exp['description'][-1]
                            moved = 0

                    else:
                        moved = 1

                    exp['job'].append(jobscript)
                    exp['date'].append(new_date)
                    exp['company'].append(companyscript)
                    exp['description'].append(description)

                for experience in exp['date']:
                    if ' · ' in experience:
                        dates, duration = experience.split(' · ')
                        parts = duration.split(' ')
                        if duration == "Less than a year":
                            total_months += 12
                        elif len(parts) == 4:
                            yearnum, yrs, monthnum, mos = parts
                            total_months += int(yearnum) * 12 + int(monthnum)
                        elif len(parts) == 2:
                            num, des = parts
                            if des.startswith("yr"):
                                total_months += int(num) * 12
                            elif des.startswith("mo"):
                                total_months += int(num)
                    else:
                        try:
                            parts = experience.split(' ')
                            if len(parts) == 4:
                                yearnum, yrs, monthnum, mos = parts
                                total_months += int(yearnum) * 12 + int(monthnum)
                            elif len(parts) == 2:
                                num, des = parts
                                if des.startswith("yr"):
                                    total_months += int(num) * 12
                                elif des.startswith("mo"):
                                    total_months += int(num)
                        except ValueError:
                            continue
                person['total months worked'].append(total_months)
                personf = pd.DataFrame(person)
                expf = pd.DataFrame(exp)
                final = pd.concat([personf, expf, eduf], axis=1)
                print(f"Profile scraped: {name}")
                return final

            else:
                return None
            
        except StaleElementReferenceException:
            if attempt < retry_attempts - 1:
                print(f"Stale element reference occurred while loading profile {url}. Retrying {attempt + 1}/{retry_attempts}...")
                time.sleep(1)
            else:
                print(f"StaleElementReferenceException for {url}, retries exhausted.")

        except TimeoutException:
            if attempt < retry_attempts - 1:
                print(f"Timeout occurred while loading profile {url}. Retrying {attempt + 1}/{retry_attempts}...")
                time.sleep(1)
            else:
                print(f"Failed to load profile {url} after {retry_attempts} attempts.")
                return None
            


# Generate keyword tags for each person scraped
def generate_keywords(profile_dict):
    def format_profile(data):
        if isinstance(data, (str, int, float)):
            return str(data)
        elif isinstance(data, list):
            return ', '.join(format_profile(item) for item in data)
        elif isinstance(data, dict):
            return '; '.join(f"{k}: {format_profile(v)}" for k, v in data.items())
        elif hasattr(data, 'to_dict'):  # For Pandas Series or DataFrames
            return format_profile(data.to_dict())
        else:
            return str(data)
        
    profile_dict = format_profile(profile_dict)

    prompt_template = """
    Extract keywords from the following profile data. The profile data is structured as a dictionary \
        with fields for 'current job', 'company', 'location', 'about', 'total months worked', 'url', and 'jobs'. \
            Each job is a dictionary with fields for 'job', 'company', 'date', and 'description'. The \
                keywords should be relevant to the person's work experience, skills, and education.

    Example input:
    {{
        "current job": "Data Science @ UCSD | Prev @ Amazon, Meta, Gallo",
        "company": UCSD
        "location": "Ceres, California, United States",
        "about": "Being a first-gen Latino, I'm passionate about being apart of a team who is innovative \
            and use their knowledge to develop and create products impacting our lives positively. Feel \
                free to reach out!",
        "total months worked": 52,
        "url": "https://www.linkedin.com/in/diegozavalza",
        "jobs": [
            {{"job": "Data Science Intern", "company": "Qualcomm Institute", "date": "Jan 2024 - Present", \
            "description": null}},
            {{"job": "Undergraduate Teaching Assistant", "company": "UCSD", "date": "Sep 2022 - Present", \
            "description": null}}
        ]
    }}

    Example output:
    ["Data Science", "UCSD", "Amazon", "Meta", "Gallo", "Qualcomm Institute", "Teaching Assistant"]

    Input:
    {profile_data}

    Output:
    """

    client = OpenAI()
    profile_data = json.dumps(profile_dict)
    prompt = prompt_template.format(profile_data=profile_data)

    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a helpful assistant that extracts keywords from profile data."},
            {"role": "user", "content": prompt}
        ]
    )

    # Correct way to access the response content
    keywords = response.choices[0].message.content.strip()
    keywords = keywords.replace('"', '').replace('[', '').replace(']', '').strip()
    return keywords.split(', ')

def search_optimizer():
    client = anthropic.Anthropic()

    entered = input("What kind of person of you want to scrape: ")

    prompt_template = """
        When given a description of the type of expert needed, you should:
        1. Analyze the requirements and identify key areas of expertise.
        2. Generate a list of relevant keywords, considering the following:
        - Industry-specific terms and jargon
        - Job titles and roles
        - Skills and competencies
        - Relevant certifications or qualifications
        - Tools or technologies specific to the field
        - If applicable, include terms in the local language of the target market
        3. Create 10 keyword groups, each containing 2-4 keywords or phrases.
        4. Ensure the keyword groups cover a wide range of relevant aspects, such as:
        - Technical expertise
        - Management or leadership experience
        - Research and development
        - Policy and regulation knowledge
        - Industry thought leadership
        - Practical application of skills
        - Academic or educational background
        5. Include terms that suggest high profile or public-facing roles (e.g., "Keynote Speaker", "Industry Influencer", "Thought Leader", "Best-Selling Author").
        6. Balance the use of specific, technical terms with more general descriptors to capture a broad range of relevant profiles.
        7. Adapt to the cultural and linguistic context of the target market when necessary.

        Your output should be a numbered list of 10 keyword groups, each on a new line.

        Your output MUST strictly follow this format and have MAXIMUM 3 words:
        1. Keyword1 Keyword2 Keyword3
        2. Keyword4 Keyword5 Keyword6
        ...

        Do not use quotes around keywords. Separate keywords with single spaces only.

        Aim to create diverse, comprehensive, and effective keyword combinations that will help users find the exact type of expert they need on LinkedIn, regardless of the field or specialty.

        Input:
        {nlPrompt}

        Output:

    """

    prompt = prompt_template.format(nlPrompt = entered)

    message = client.messages.create(
        model="claude-3-5-sonnet-20240620",
        max_tokens=1000,
        temperature=0,
        system="You are an AI assistant specialized in generating LinkedIn search keyword combinations to find experts across various fields, industries, and specialties. Your task is to create keyword groups that will help identify high-profile individuals suitable for speaking at events, providing expert commentary, or fulfilling specific professional roles.",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }
        ]
    )

    output = message.content[0].text.strip()
    output = re.sub(r'["\']', '', output)
    output = re.sub(r'\n+', '\n', output)
    print("These are the possible inputs:\n" + output)

    lines = output.split('\n')
    keyword_groups = []
    for line in lines:
        keyword_groups.append(re.sub(r'^\d+\s*', '', line).strip('. '))

    return keyword_groups


def process_page(driver, keywords, page):
    profiles = search(driver, keywords, page)
    results = []
    for person in profiles:
        final = get_profile(driver, person)
        if final is not None:
            results.append(final)
            print(f"Processed profile: {person}")
    return results

if __name__ == "__main__":
    os.environ["OPENAI_API_KEY"] = ""
    os.environ["ANTHROPIC_API_KEY"] = ""

    un = input("Enter your linkedin username:")
    pw = input("Enter your linkedin password:")

    driver = setup(un, pw)
    
    promptpagepairs = []
    cleaned = []

    choosing = input("Do you have your own key words? (Type No to get keyword recommendations from AI) \n")

    if choosing == "No":
        here = search_optimizer()
        print("Choose the keyword pairs you want to use. Add the amount of pages too (10 profiles/page). For the first group of keywords scraping five pages, TYPE: 1, 5")
        print("To indicate you finished prompting, TYPE: end. You will also have a chance to enter your own keywords.")
        number = 1
        while True: 
            user_input = input("Which keyword set would you like to search up, and how many pages?" + " This is set number " + str(number) + "\n")

            if user_input == "end":
                break

            number += 1
            promptpagepairs.append(user_input)

        for entry in promptpagepairs:
            entry.strip('"" ')
            each = entry.split(', ')
            each[0] = here[int(each[0]) - 1]
            cleaned.append(each)

    number = 1
    print("Now, please enter your key words as well as how many pages you would like to scrape. Example: finance McKinsey, 1 \nTo indicate you finished prompting, TYPE: end.")
    while True: 
        user_input = input("Which keyword set would you like to search up, and how many pages?" + " This is set number " + str(number) + "\n")

        if user_input == "end":
            break
        
        user_input.strip('"" ')
        each = user_input.split(', ')
        cleaned.append(each)
        number += 1

    for pair in cleaned:
        pages = int(pair[1])
        prompt = pair[0]
        tracker = pd.DataFrame()

        with ThreadPoolExecutor(max_workers = 1) as executor:
            futures = [executor.submit(process_page, driver, prompt, page) for page in range(1, pages + 1)]
            results = []
            for future in as_completed(futures):
                page_results = future.result()
                if page_results:
                    results.extend(page_results)

        if results:
            tracker = pd.concat(results, axis = 0)
            tracker['name'] = tracker['name'].ffill()
            tracker['url'] = tracker['url'].str.strip().str.lower()
            
            structured_data = {}

            for index, row in tracker.iterrows():
                name = row['name']
                if name not in structured_data:
                    structured_data[name] = {
                        'current job': row['current job'],
                        'currcompany': row['currcompany'],
                        'location': row['location'],
                        'about': row['about'],
                        'total months worked': row['total months worked'],
                        'url': row['url'],
                        'jobs': []
                    }
                
                job_dict = {
                    'job': str(row['job']).replace('\n', ' ').strip(),
                    'company': str(row['company']).replace('\n', ' ').strip(),
                    'date': row['date'],
                    'description': row['description']
                }
                
                structured_data[name]['jobs'].append(job_dict)

            keywords_data = {}

            for name, profile in structured_data.items():
                if not profile['about'] or profile['about'].strip() == '':
                    jobs_summary = []
                    for job in profile['jobs']:
                        job_info = f"{job['job']} at {job['company']} ({job['date']})"
                        jobs_summary.append(job_info)
                        profile['about'] = "Career Summary: " + " | ".join(jobs_summary)

                keywords = generate_keywords(profile)
                if isinstance(keywords, (list, dict)):
                    keywords = ', '.join(map(str, keywords if isinstance(keywords, list) else keywords.values()))

                keywords_data[profile['url']] = keywords

            keywords_df = pd.DataFrame.from_dict(keywords_data, orient='index', columns=['keywords'])
            keywords_df.index.name = 'url'
            keywords_df = keywords_df.reset_index()
            keywords_df['url'] = keywords_df['url'].str.strip().str.lower()

            final_df = pd.DataFrame.from_dict(structured_data, orient='index')
            final_df = final_df.reset_index().rename(columns={'index': 'name'})
            final_df['url'] = final_df['url'].str.strip().str.lower()

            merged_df = pd.merge(final_df, keywords_df, on='url', how='left')
            merged_df = merged_df.drop_duplicates(subset='name', keep='first')
            merged_df['currcompany'].str.replace('\n', '').str.strip()

            merged_df.to_csv('pwk_' + prompt + '.csv', sep=',', encoding='utf-8', index=False)
        
        else:
            print("No data was scraped.")