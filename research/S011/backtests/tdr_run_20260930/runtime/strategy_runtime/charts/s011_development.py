"""S011 research chart using the existing platform visual contract."""
from .common import Panel,UnifiedStrategyCharts


class S011DevelopmentCharts(UnifiedStrategyCharts):
    def panels(self,context):
        # The host exposes target_position here, not the original pressure score.
        return (Panel(('target_position',),'目标仓位（信号日）','#60a5fa',line_shape='hv'),)
