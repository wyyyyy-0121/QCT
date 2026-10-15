"""Additional institution-owned indexes only; no workbooks or error answers."""
import discover_source_metadata_v4 as discovery

discovery.OUT = discovery.ROOT / 'source_discovery/metadata_v6'
discovery.PAGES = {
    'iowa_state_decision_tools': 'https://www.extension.iastate.edu/agdm/decisiontools.html',
    'iowa_state_copyright': 'https://www.extension.iastate.edu/agdm/info/copyright.html',
    'oklahoma_state_budgets': 'https://extension.okstate.edu/programs/farm-management-and-finance/budgets/',
    'nlr_jedi': 'https://www.nlr.gov/analysis/jedi',
    'nrel_jedi_archival_redirect': 'https://www.nrel.gov/analysis/jedi/models.html',
    'penn_state_enterprise_budgets': 'https://extension.psu.edu/business-and-operations/business-management/financial-management/enterprise-budgets',
    'nz_treasury_tools_index': 'https://www.treasury.govt.nz/information-and-services/state-sector-leadership/investment-management/plan-investment-choices/cost-benefit-analysis-including-public-sector-discount-rates',
    'worldbank_project_appraisal': 'https://ppp.worldbank.org/public-private-partnership/library/financial-modeling-ppp-projects',
}

if __name__ == '__main__':
    discovery.main()
