# Risk ownership: TDR-12
"""Converged delivery schemas reject ambiguous identity and illegal values."""
import pytest
from czsc_trader.research_tools import delivery as d


@pytest.mark.parametrize('report', [' \n\t'], ids=['blank-text'])
def test_TDR_12_C02_delivery_requires_nonempty_researcher_report(report):
    with pytest.raises((TypeError, ValueError)):
        d.DeliveryContent(d.ComponentPanel((), "negative finding"), d.DeliveryStatus.COMPLETE,
                          (), (), report=report)
