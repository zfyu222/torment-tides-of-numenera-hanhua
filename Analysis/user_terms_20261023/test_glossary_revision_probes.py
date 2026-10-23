import unittest
import ainiee_bridge as bridge
from workflow_quality import glossary_revision_probes, glossary_match_meaning


class RevisionProbeTests(unittest.TestCase):
    @staticmethod
    def glossary(*pairs):
        return {'terms':[{'source':a,'recommended_translation':b} for a,b in pairs]}

    def equivalent(self,old,new,texts):
        options={'case_sensitive':False,'whole_word':True}
        probes=glossary_revision_probes(old,new)
        expected=[];actual=[]
        for text in texts:
            full=glossary_match_meaning(bridge.matched_terms(old,[text],options))!=glossary_match_meaning(bridge.matched_terms(new,[text],options))
            candidate=probes is None or any(bridge.matched_terms(p,[text],options) for p in probes)
            expected.append(full);actual.append(candidate and full)
        self.assertEqual(expected,actual)

    def test_rename_and_removed_overlapping_bare_word(self):
        old=self.glossary(('numenera','旧音译'),('bonded','配偶'),('Bonded Items','绑定物品'),('other','其他'))
        new=self.glossary(('numenera','扭蒙拉'),('Bonded Items','绑定物品'),('other','其他'))
        self.equivalent(old,new,['Numenera artifact','my bonded','Bonded Items','other words','unrelated','numeneras','{numenera}'])

    def test_added_longer_match_and_unicode_quote_normalization(self):
        old=self.glossary(("Don's",'甲'),('alpha','阿尔法'))
        new=self.glossary(("Don's",'乙'),('alpha','阿尔法'),('alpha beta','阿尔法贝塔'))
        self.equivalent(old,new,["Don’s story","Don's story",'alpha beta','alpha alone','unrelated'])

    def test_reordered_or_duplicate_identity_falls_back(self):
        old=self.glossary(('alpha','甲'),('beta','乙'))
        self.assertIsNone(glossary_revision_probes(old,self.glossary(('beta','乙'),('alpha','甲'))))
        self.assertIsNone(glossary_revision_probes(old,self.glossary(('alpha','甲'),('alpha','乙'))))

    def test_renumbered_ref_is_not_a_semantic_change(self):
        a=[{'ref':'terms:1','src':'other','dst':'其他'}]
        b=[{'ref':'terms:0','src':'other','dst':'其他'}]
        self.assertEqual(glossary_match_meaning(a),glossary_match_meaning(b))
        b[0]['dst']='另一译名'
        self.assertNotEqual(glossary_match_meaning(a),glossary_match_meaning(b))


if __name__=='__main__':unittest.main()
