import unittest
import pandas as pd
import numpy as np
from pipeline import prepare,features
class PipelineTests(unittest.TestCase):
    def test_no_future_features(self):
        idx=pd.date_range('2023-01-01',periods=80,freq='min')
        d=pd.DataFrame({'water_pH':np.arange(80)/100+7,'water_temp':np.arange(80)/100+24},index=idx)
        a=features(d);d.iloc[41:]=999;b=features(d)
        pd.testing.assert_frame_equal(a.iloc[:41],b.iloc[:41])
    def test_gap_is_not_row_shift(self):
        idx=pd.to_datetime(['2023-01-01 00:00','2023-01-01 00:05','2023-01-01 00:35'])
        d=pd.DataFrame({'water_pH':[7,8,9],'water_temp':[24,25,26]},index=idx)
        future=d.copy();future.index-=pd.Timedelta(minutes=30)
        pairs=d.join(future.add_suffix('_target'),how='inner')
        self.assertEqual(len(pairs),1);self.assertEqual(pairs.iloc[0].water_pH_target,9)
        self.assertTrue(np.isnan(features(d).iloc[-1].water_pH_lag5))
    def test_cleaning_preserves_uncomfortable_values(self):
        d=pd.DataFrame({'created_date':['1/1/2023 00:00']*4,'water_pH':[5.5,9.5,15.5,7],'water_temp':[22,27,24,24]})
        clean,q=prepare(d);self.assertEqual(q['rejected_rows'],1);self.assertEqual(clean.iloc[0].water_pH,7)
    def test_tds_exact_horizon_and_no_capping(self):
        from pipeline import HORIZON, exceedance
        raw=pd.DataFrame({"created_date":["1/1/2023 00:00","1/1/2023 00:00","1/1/2023 00:30","1/1/2023 00:32"],
                          "TDS":[400,600,700,-1]})
        d,info=prepare(raw,["TDS"])
        self.assertEqual(info["rejected_rows"],1)
        self.assertEqual(d.iloc[:,0].tolist(),[500,700])
        p=d.join(d.TDS.shift(freq=-HORIZON).rename("actual"),how="inner")
        self.assertEqual(p.iloc[0].actual,700)
        x=features(d)
        self.assertEqual(x.iloc[1].TDS_lag30,500)
        self.assertTrue(np.isnan(x.iloc[1].TDS_lag5))
        conf=exceedance([500,501,502],[500,499,510])
        self.assertEqual((conf["tp"],conf["fn"],conf["tn"]), (1,1,1))
if __name__=='__main__': unittest.main()
