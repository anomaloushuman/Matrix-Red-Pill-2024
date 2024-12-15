import json
import statistics

def parse_election_data(pennsylvania_file, pageneral_file):
    with open(pennsylvania_file, 'r') as file:
        pennsylvania_data = json.load(file)

    with open(pageneral_file, 'r') as file:
        pageneral_data = json.load(file)

    results = {}
    results['county_by_vote_type'] = []
    results['potential_fraud'] = []  # List to hold potential fraud cases

    absentee_ratios = []  # List to hold absentee vote ratios for statistical analysis

    # First pass: Collect absentee ratios
    for county in pageneral_data['county_by_vote_type']:
        total_votes = county['votes']
        results_dict = county['results']
        
        if total_votes > 0:
            absentee_votes = results_dict.get('absentee', 0)  # Assuming absentee votes are stored here
            absentee_ratio = absentee_votes / total_votes
            absentee_ratios.append(absentee_ratio)

    # Calculate average absentee ratio and standard deviation
    if absentee_ratios:
        average_absentee_ratio = statistics.mean(absentee_ratios)
        std_dev_absentee_ratio = statistics.stdev(absentee_ratios)

    # Second pass: Check for potential fraud
    for county in pageneral_data['county_by_vote_type']:
        precinct_id = county['precinct_id']
        locality_name = county['locality_name']
        vote_type = county['vote_type']
        results_dict = county['results']
        total_votes = county['votes']

        # Create a structured entry for each county
        county_entry = {
            'precinct_id': precinct_id,
            'locality_name': locality_name,
            'vote_type': vote_type,
            'results': {
                'bidenj': results_dict['bidenj'],
                'trumpd': results_dict['trumpd'],
                'jorgensenj': results_dict['jorgensenj'],
                'total_votes': total_votes,
                'is_reporting': county['is_reporting'],
            }
        }

        # Check for absentee ballot fraud indicators
        if vote_type == 'absentee' and total_votes > 0:
            absentee_votes = results_dict.get('absentee', 0)  # Assuming absentee votes are stored here
            absentee_ratio = absentee_votes / total_votes
            
            # Flag if the absentee ratio is significantly higher than average (within 1 standard deviation)
            if absentee_ratio > (average_absentee_ratio + std_dev_absentee_ratio):
                # Determine which candidate received the majority of absentee votes
                candidate_votes = {
                    'bidenj': results_dict['bidenj'],
                    'trumpd': results_dict['trumpd'],
                    'jorgensenj': results_dict['jorgensenj'],
                }
                max_candidate = max(candidate_votes, key=candidate_votes.get)
                results['potential_fraud'].append({
                    'precinct_id': precinct_id,
                    'locality_name': locality_name,
                    'issue': 'Statistically improbable high percentage of absentee ballots',
                    'absentee_votes': absentee_votes,
                    'total_votes': total_votes,
                    'absentee_ratio': absentee_ratio,  # Added absentee ratio
                    'candidate_with_most_votes': max_candidate,
                    'votes_for_candidate': candidate_votes[max_candidate],
                })

        results['county_by_vote_type'].append(county_entry)

    return results

def analyze_absentee_ballots(county_data):
    potential_fraud = []
    for county in county_data['county_by_vote_type']:
        if county['vote_type'] == 'absentee':
            # Calculate metrics for absentee ballots
            total_votes = county['results']['total_votes']
            biden_votes = county['results']['bidenj']
            trump_votes = county['results']['trumpd']
            # Example metric: ratio of Biden votes to total votes
            biden_ratio = biden_votes / total_votes if total_votes > 0 else 0
            
            # Check for abnormalities (example condition)
            if biden_ratio > 0.7:  # Adjust this condition as needed
                potential_fraud.append({
                    "locality": county['locality_name'],
                    "biden_votes": biden_votes,
                    "trump_votes": trump_votes,
                    "biden_ratio": biden_ratio,
                    "total_votes": total_votes
                })

    return potential_fraud

def summarize_vote_ratios(county_data, flagged_fraud):
    total_votes = {
        'absentee': 0,
        'biden': 0,
        'trump': 0,
        'jorgensen': 0,
        'total': 0
    }

    for county in county_data['county_by_vote_type']:
        # Skip flagged fraud data
        if any(fraud['locality'] == county['locality_name'] for fraud in flagged_fraud):
            continue
        
        results = county['results']
        total_votes['absentee'] += results.get('absentee', 0)
        total_votes['biden'] += results['bidenj']
        total_votes['trump'] += results['trumpd']
        total_votes['jorgensen'] += results['jorgensenj']
        total_votes['total'] += results['total_votes']

    # Calculate ratios
    ratios = {
        'biden_ratio': total_votes['biden'] / total_votes['total'] if total_votes['total'] > 0 else 0,
        'trump_ratio': total_votes['trump'] / total_votes['total'] if total_votes['total'] > 0 else 0,
        'jorgensen_ratio': total_votes['jorgensen'] / total_votes['total'] if total_votes['total'] > 0 else 0,
    }

    return total_votes, ratios

if __name__ == "__main__":
    # Define the file paths
    pennsylvania_file = 'pennsylvania.json'
    pageneral_file = 'PAGeneralConcatenator-latest.json'

    # Parse the election data
    election_data = parse_election_data(pennsylvania_file, pageneral_file)

    # Update the potential_fraud key
    election_data['potential_fraud'] = analyze_absentee_ballots(election_data)

    # Call the summary function and display results
    total_votes, ratios = summarize_vote_ratios(election_data, election_data['potential_fraud'])

    # Print or log the summary report
    print("Total Votes Summary:")
    print(f"Absentee Votes: {total_votes['absentee']}")
    print(f"Biden Votes: {total_votes['biden']} (Ratio: {ratios['biden_ratio']:.2%})")
    print(f"Trump Votes: {total_votes['trump']} (Ratio: {ratios['trump_ratio']:.2%})")
    print(f"Jorgensen Votes: {total_votes['jorgensen']} (Ratio: {ratios['jorgensen_ratio']:.2%})")
    print(f"Total Votes: {total_votes['total']}")

    # Generate a report
    print(json.dumps(election_data, indent=4))  # Pretty print the results