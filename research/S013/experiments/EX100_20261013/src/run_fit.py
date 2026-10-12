"""Publish exact inputs before fitting and keep the two rounds bound to them."""
import sys
import governance as g
import driver
import input_adapter

def run(number):
    exp=g.ExperimentRef('S013',f'EX{number:03}_20261013'); p=exp.resolve(g.ROOT)/'protocols'
    paths=[g.WORK/'inputs/features.csv',g.WORK/'execution/model/labels.csv',g.WORK/'execution/model/attempts.csv',g.WORK/'input_adapter.py']
    actual={x.relative_to(g.ROOT).as_posix():g.digest(x) for x in paths}
    if number==99:
        if (p/'fit_input_binding.json').exists(): raise ValueError('No implicit second fit')
        source=g.WORK/'run_fit.py'
        refs={x.relative_to(g.ROOT).as_posix():g.put(exp,x) for x in [*paths,source]}
        binding={'status':'INPUTS_FROZEN_BEFORE_FIT','input_sha256':actual,'input_references':refs,
            'fit_runner_sha256':g.digest(source),'model_fits_before_binding':0}
        g.write(p/'fit_input_binding.json',binding)
        g.write(p/'fit_input_binding_reference.json',g.put(exp,p/'fit_input_binding.json'))
    elif number==100:
        prior=g.ROOT/'research/S013/experiments/EX099_20261013/protocols'
        reference=g.read(prior/'fit_input_binding_reference.json')
        binding=g.read(g.public(reference))
        if actual!=binding['input_sha256'] or g.digest(g.WORK/'run_fit.py')!=binding['fit_runner_sha256']:
            raise ValueError('Cross-round input/runner drift')
        g.write(p/'fit_input_binding.json',{**binding,'parent_binding_reference':reference})
        g.write(p/'fit_input_binding_reference.json',g.put(exp,p/'fit_input_binding.json'))
    else: raise ValueError('Only approved rounds')
    for reference in binding['input_references'].values(): g.public(reference)
    # Bind the explicit producer field adapter; numerical kernels stay frozen.
    driver.core=input_adapter.core
    driver.fit(number)

if __name__=='__main__': run(int(sys.argv[1]))
