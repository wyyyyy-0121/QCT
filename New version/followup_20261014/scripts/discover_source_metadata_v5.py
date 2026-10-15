"""Resolve official index URLs and repository license filenames, metadata only."""
import discover_source_metadata_v4 as discovery

discovery.OUT = discovery.ROOT / 'source_discovery/metadata_v5'
discovery.PAGES = {
    'renewables_pinned_tree': 'https://api.github.com/repos/RenewablesPro/rvi-sample-models/git/trees/1e49ec79613c77c3fa6f8532b4e303b473f85506?recursive=1',
    'uk_tag_data_book': 'https://www.gov.uk/government/publications/tag-data-book',
    'uk_electricity_generation_costs_2023': 'https://www.gov.uk/government/publications/electricity-generation-costs-2023',
    'nist_building_life_cycle': 'https://www.nist.gov/services-resources/software/building-life-cycle-cost-programs',
    'damodaran_home': 'https://pages.stern.nyu.edu/~adamodar/',
}

if __name__ == '__main__':
    discovery.main()
