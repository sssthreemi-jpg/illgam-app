const $ = id => document.getElementById(id)
let token = null
let myCompany = null
let lastReviewInput = null
const $select = id => document.getElementById(id)

function showError(msg){
  const formError = $('form-error')
  if(formError && $('result-page').style.display === 'none'){
    formError.textContent = msg
    return
  }
  const el = $('result')
  el.innerHTML = `<div style="color:#b91c1c;font-weight:700">오류</div><div style="margin-top:6px">${msg}</div>`
  el.style.borderColor = '#f8d7da'
}

function showResult(obj){
  const el = $('result')
  el.innerHTML = `<pre style="white-space:pre-wrap;margin:0">${escapeHtml(JSON.stringify(obj, null, 2))}</pre>`
  el.style.borderColor = '#dbefff'
}

async function post(path, body){
  const res = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json', ...(token?{Authorization:'Bearer '+token}:{})}, body: JSON.stringify(body)})
  const data = await res.json().catch(()=>null)
  if(!res.ok){
    const detail = data && (data.detail || data.message)
    throw new Error(detail || `서버 오류 (${res.status})`)
  }
  return data
}

$('login').onclick = async ()=>{
  const username = $('username').value
  const password = $('password').value
  if(!username || !password){ showError('사용자명과 비밀번호를 입력하세요'); return }
  try{
    // try real API first
    const res = await fetch('/api/auth/login', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({username,password})})
    if(res.ok){
      const j = await res.json(); if(j && j.access_token){ token = j.access_token; document.getElementById('login-overlay').style.display='none'; document.getElementById('app').style.display='block'; await loadMyCompany(); return }
    }
  }catch(e){ /* ignore and fallback to mock */ }

  // fallback mock for development
  if(username === 'admin' && password === 'adminpass'){
    token = 'dev-token-admin'
    document.getElementById('login-overlay').style.display='none'
    document.getElementById('app').style.display='block'
    myCompany = {company:'admin'}
    $('rawdata-button').style.display = 'inline-block'
    $('mycompany').textContent = JSON.stringify(myCompany)
    $('company').value = myCompany.company
    $('company').removeAttribute('disabled')
    return
  }
  // other mock: accept any non-empty creds in dev
  if(window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost'){
    token = 'dev-token'
    document.getElementById('login-overlay').style.display='none'
    document.getElementById('app').style.display='block'
    myCompany = {company: username}
    $('mycompany').textContent = JSON.stringify(myCompany)
    $('company').value = myCompany.company
    if(myCompany.company !== 'admin') $('company').setAttribute('disabled','true')
    $('rawdata-button').style.display = 'none'
    return
  }
  showError('로그인 실패')
}

// related_format picker: update textarea placeholder/sample
const relatedFormatEl = document.getElementById('related_format')
const relatedSalesEl = document.getElementById('related_sales')
if(relatedFormatEl && relatedSalesEl){
  relatedFormatEl.addEventListener('change', ()=>{
    const v = relatedFormatEl.value
    if(v === 'json'){
      relatedSalesEl.value = '{"대웅제약":900000}'
    } else {
      relatedSalesEl.value = '대웅제약,900000\n회사B,100000'
    }
  })
}

// Table helpers for related sales and tax adjustments
function getRelatedFromTable(){
  const tbody = document.querySelector('#related_table tbody')
  if(!tbody) return null
  const related = {}
  Array.from(tbody.querySelectorAll('tr')).forEach(tr=>{
    const name = tr.dataset.company || ''
    const amtEl = tr.querySelector('.ramt')
    const amt = Number(amtEl && amtEl.value ? amtEl.value : 0)
    if(name) related[name] = amt
  })
  return related
}

function getTaxFromTable(){
  const tbody = document.querySelector('#tax_table tbody')
  if(!tbody) return null
  const obj = {}
  Array.from(tbody.querySelectorAll('tr')).forEach(tr=>{
    const name = tr.dataset.taxItem || ''
    const amtEl = tr.querySelector('.tamt')
    const amt = Number(amtEl && amtEl.value ? amtEl.value : 0)
    if(name) obj[name] = amt
  })
  return obj
}

// add/remove row handlers
document.addEventListener('click', (e)=>{
  if(e.target && e.target.id === 'add_tax_row'){
    return
  }
})

document.addEventListener('input', (e)=>{
  if(e.target && e.target.classList.contains('tamt')) updateTaxTotal()
})

function updateTaxTotal(){
  const total = Array.from(document.querySelectorAll('#tax_table .tamt'))
    .reduce((sum, input) => sum + (Number(input.value) || 0), 0)
  if($('tax-total')) $('tax-total').value = `${formatNum(total)}원`
}

// Download handlers: simple CSV export and print
document.getElementById('excel-download')?.addEventListener('click', ()=>{
  // build CSV from related and tax tables
  const related = getRelatedFromTable() || {}
  const tax = getTaxFromTable() || {}
  let csv = 'Section,Name,Amount\n'
  Object.entries(related).forEach(([k,v])=> csv += `Related,${k},${v}\n`)
  Object.entries(tax).forEach(([k,v])=> csv += `TaxAdjust,${k},${v}\n`)
  const blob = new Blob([csv], {type:'text/csv;charset=utf-8;'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a'); a.href = url; a.download = 'report_export.csv'; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
})

document.getElementById('pdf-download')?.addEventListener('click', ()=>{
  window.print()
})

async function loadMyCompany(){
  const res = await fetch('/api/my-company',{headers: token?{Authorization:'Bearer '+token}:{}})
  if(!res.ok){ showError('내 법인 정보를 불러오지 못했습니다'); return }
  const j = await res.json()
  myCompany = j
  $('mycompany').textContent = JSON.stringify(j)
  $('hint').textContent = ''
  const companySelect = $('company')
  const companySize = $('company_size')
  // Populate only the public company-name list. Sensitive ownership data stays server-side.
  try{
    const c = await fetch('/api/companies',{headers: token?{Authorization:'Bearer '+token}:{}})
    if(c.ok){
      const cl = await c.json()
      companySelect.innerHTML = '<option value="">법인을 선택하세요</option>'
      const companies = (cl.companies || []).filter(name => name !== '기타')
      companies.forEach(name=>{
        const option = document.createElement('option')
        option.value = name
        option.textContent = name
        companySelect.appendChild(option)
      })
      renderRelatedCompanies(companies)
    }
  }catch(e){ /* ignore */ }

  if(j.company !== 'admin'){
    companySelect.value = j.company || ''
    companySelect.setAttribute('disabled','true')
    $('hint').textContent = '(관리자 아님 — 법인 필드 잠김)'
  } else {
    $('rawdata-button').style.display = 'inline-block'
    companySelect.removeAttribute('disabled')
    if(companySelect.options.length > 1 && !companySelect.value) companySelect.value = companySelect.options[1].value
  }
  updateCompanySize()
  if(j.company !== 'admin' && j.size && ['일반','중견','중소'].includes(j.size)){
    $('company_size').value = j.size
  }
}

function renderRelatedCompanies(companies){
  const tbody = document.querySelector('#related_table tbody')
  if(!tbody) return
  tbody.innerHTML = [...companies, '기타법인'].map(name => `
    <tr data-company="${escapeHtml(name)}"><td>${escapeHtml(name)}</td><td><input class="ramt" type="number" min="0" value="0" placeholder="0"></td></tr>
  `).join('')
}

function updateCompanySize(){
  const selected = $('company') && $('company').selectedOptions[0]
  const size = selected && selected.dataset.size
  if($('company_size') && size) $('company_size').value = size
}

$('company')?.addEventListener('change', updateCompanySize)

$('evaluate').onclick = async ()=>{
  if($('form-error')) $('form-error').textContent = ''
  // validation
  try{
    // read related sales from table if present, otherwise fallback to textarea/csv/json
    let related = {}
    const tableRelated = getRelatedFromTable()
    if(tableRelated && Object.keys(tableRelated).length>0){
      related = tableRelated
    } else {
      const rawRelated = (document.getElementById('related_sales') && document.getElementById('related_sales').value) || ''
      if(($select('related_format') && $select('related_format').value === 'csv') || (rawRelated.indexOf('\n') !== -1 && rawRelated.indexOf('{') === -1)){
        rawRelated.split(/\r?\n/).forEach(line=>{
          const [name,amt] = line.split(',').map(s=>s && s.trim())
          if(name){ related[name] = Number(amt || 0) }
        })
      } else {
        try{ related = JSON.parse(rawRelated || '{}') }catch(e){ related = {} }
      }
    }
    const company = $('company').value
    if(!company){ showError('법인을 선택하세요'); return }
    // ensure company matches logged-in user's company unless admin
    if(myCompany && myCompany.company !== 'admin' && company !== myCompany.company){ showError('자기 법인만 판정할 수 있습니다'); return }
    const operating_income = Number($('operating_income').value)
    const corporate_tax = Number($('corporate_tax').value)
    const total_sales = Number($('total_sales').value)
    if(Number.isNaN(operating_income) || Number.isNaN(corporate_tax) || Number.isNaN(total_sales)){
      showError('숫자 필드에 유효한 값을 입력하세요'); return
    }
    if(total_sales < 0 || operating_income < 0 || corporate_tax < 0){ showError('음수 값은 허용되지 않습니다'); return }

    // read tax adjustments from table if present, otherwise fallback to textarea
    let tax_adjustments = {}
    const tableTax = getTaxFromTable()
    if(tableTax && Object.keys(tableTax).length>0){ tax_adjustments = tableTax }
    else {
      try{ tax_adjustments = JSON.parse(($('tax_adjustments') && $('tax_adjustments').value) || '{}') }catch(e){ tax_adjustments = {} }
    }

    const body = {
      company, operating_income, corporate_tax, total_sales, related_sales: related, tax_adjustments
    }
    const reviewPath = myCompany && myCompany.company === 'admin' ? '/api/admin/evaluate-review' : '/api/evaluate'
    const r = await post(reviewPath, body)
    if(r && typeof r === 'object' && r.company && r.reason) {
      lastReviewInput = {company, companySize: $('company_size').value, operating_income, corporate_tax, total_sales, related, tax_adjustments}
      const isAdmin = myCompany && myCompany.company === 'admin'
      renderReport(r, {...lastReviewInput, isAdmin})
      $('rawdata-button').style.display = isAdmin ? 'inline-block' : 'none'
      $('input-page').style.display = 'none'
      $('result-page').style.display = 'block'
    } else {
      showError('서버 응답을 확인하세요')
    }
  } catch(e){ showError(e.message || '서버 응답을 확인하세요'); }
}

$('back-to-input').onclick = ()=>{
  $('result-page').style.display = 'none'
  $('input-page').style.display = ''
  if($('form-error')) $('form-error').textContent = ''
}

$('rawdata-button').onclick = ()=>{
  if(!myCompany || myCompany.company !== 'admin' || !lastReviewInput) return
  renderRawData(lastReviewInput)
  $('result-page').style.display = 'none'
  $('rawdata-page').style.display = 'block'
}

$('rawdata-back').onclick = ()=>{
  $('rawdata-page').style.display = 'none'
  $('result-page').style.display = 'block'
}

function renderRawData(input){
  const rows = Object.entries(input.related || {}).map(([name, amount]) => `<tr><td>${escapeHtml(name)}</td><td style="text-align:right">${formatNum(amount)}원</td></tr>`).join('')
  const taxRows = Object.entries(input.tax_adjustments || {}).map(([name, amount]) => `<tr><td>${escapeHtml(name)}</td><td style="text-align:right">${formatNum(amount)}원</td></tr>`).join('')
  $('rawdata-content').innerHTML = `
    <div class="report-note"><strong>관리자 RAWDATA</strong><br>이번 검토 요청에 입력되어 서버로 전송된 원본 입력값입니다. 서버의 지분율·주주별 원본 데이터는 보안상 표시하지 않습니다.</div>
    <section class="report-section"><h3>기본정보</h3><table class="raw-table"><tbody>
      <tr><th>법인명</th><td>${escapeHtml(input.company)}</td></tr>
      <tr><th>기업 구분</th><td>${escapeHtml(input.companySize || '')}</td></tr>
      <tr><th>총매출</th><td style="text-align:right">${formatNum(input.total_sales)}원</td></tr>
      <tr><th>영업이익</th><td style="text-align:right">${formatNum(input.operating_income)}원</td></tr>
      <tr><th>법인세 상당액</th><td style="text-align:right">${formatNum(input.corporate_tax)}원</td></tr>
    </tbody></table></section>
    <section class="report-section"><h3>특수관계자 세부매출 원본</h3><table class="raw-table"><thead><tr><th>거래처명</th><th>매출액</th></tr></thead><tbody>${rows || '<tr><td colspan="2">입력된 내역이 없습니다.</td></tr>'}</tbody></table></section>
    <section class="report-section"><h3>세무조정내역 원본</h3><table class="raw-table"><thead><tr><th>조정 항목</th><th>금액</th></tr></thead><tbody>${taxRows || '<tr><td colspan="2">입력된 내역이 없습니다.</td></tr>'}</tbody></table></section>
  `
}

$('result-back-to-input').onclick = ()=> $('back-to-input').click()

function formatNum(n){ if(n===undefined || n===null) return '—'; if(typeof n==='number') return n.toLocaleString(); try{ return Number(n).toLocaleString() }catch(e){ return String(n) }}

function renderReport(r, input){
  const el = $('result')
  const judgment = r.reason || r.judgement || r.summary || '판정 결과 없음'
  const isTaxable = Boolean(r.taxable || r.gift_tax_total > 0)
  const relatedTotal = Number(r.related_sales_total || 0)
  const relatedRatio = Number(r.related_sales_ratio || 0)
  const normalRatio = Number(r.normal_ratio || 0)
  const relatedRows = Object.entries(input.related || {}).map(([name, amount]) => `
    <tr><td>${escapeHtml(name)}</td><td class="amount">${formatNum(amount)}원</td></tr>`).join('')
  const taxRows = Object.entries(input.tax_adjustments || {}).map(([name, amount]) => `
    <tr><td>${escapeHtml(name)}</td><td class="amount">${formatNum(amount)}원</td></tr>`).join('')
  const emptyRow = '<tr><td colspan="2" class="muted">입력된 내역이 없습니다.</td></tr>'
  const taxTotal = Object.values(input.tax_adjustments || {}).reduce((sum, v) => sum + (Number(v) || 0), 0)
  const taxTotalRow = taxRows ? `<tr class="total-row"><th>합계 (영업이익 가감액)</th><td class="amount">${formatNum(taxTotal)}원</td></tr>` : ''
  const adminLogic = input.isAdmin ? `
    <section class="logic-box"><h3>관리자용 계산 로직 검토</h3>
      <ol>
        <li>선택한 법인의 기업 구분에 따라 정상 거래 비율과 보유 요건 기준을 서버에서 적용합니다.</li>
        <li>입력한 특수관계자 매출을 합산하고 총매출 대비 특수관계 매출 비율을 계산합니다.</li>
        <li>세무조정 후 영업이익과 법인세 상당액을 반영해 과세 검토 대상 금액을 산출합니다.</li>
        <li>서버에 보관된 지분·관계 데이터를 적용해 증여의제 금액을 계산합니다.</li>
        <li>증여의제 금액에 누진세율을 적용해 산출 증여세와 과세 여부를 판정합니다.</li>
      </ol>
      <div class="logic-formula"><strong>검토 산식 요약</strong><br>
        특수관계 매출 비율 = 특수관계 매출 합계 ÷ 총매출<br>
        증여의제 금액 = 세후 영업이익 × 조정 비율 × 보유 요건 반영값<br>
        산출 증여세 = 증여의제 금액에 세율 및 누진공제 적용<br>
        <span class="muted">※ 실제 지분율과 주주별 원본 데이터는 보안상 화면에 표시하지 않습니다.</span>
      </div>
      <div class="report-section" style="overflow:auto"><h3>주주별 계산 상세</h3>
        <table class="report-table detail-table"><thead><tr><th>구분</th><th>지분율</th><th>과세제외매출</th><th>제외 후 특수관계 매출 비율</th><th>세후 영업이익</th><th>증여의제이익</th><th>산출 증여세</th><th>판정</th></tr></thead><tbody>
          ${(r.shareholder_details || []).map(detail => `<tr><td>${escapeHtml(detail.name)} (${escapeHtml(detail.code)})</td><td class="amount">${(Number(detail.holding_ratio) * 100).toFixed(2)}%</td><td class="amount">${formatNum(detail.excluded_sales)}원</td><td class="amount">${(Number(detail.adjusted_related_ratio) * 100).toFixed(2)}%</td><td class="amount">${formatNum(detail.after_tax_operating_income)}원</td><td class="amount">${formatNum(detail.deemed_gift_income)}원</td><td class="amount">${formatNum(detail.gift_tax)}원</td><td>${detail.taxable ? '<span class="report-status yes">대상</span>' : '<span class="report-status no">비대상</span>'}</td></tr>`).join('')}
          <tr class="total-row"><th colspan="5">총합</th><td class="amount">${formatNum(r.deemed_gift_total)}원</td><td class="amount">${formatNum(r.gift_tax_total)}원</td><td></td></tr>
        </tbody></table>
        <div class="hint">관리자 인증에서만 표시되는 상세값입니다.</div>
      </div>
    </section>` : ''

  el.innerHTML = `
    <div class="report-note"><span class="report-status ${isTaxable ? 'yes' : 'no'}">${isTaxable ? '과세대상' : '해당없음'}</span><div style="margin-top:8px">${escapeHtml(judgment)}</div></div>

    <section class="report-section"><h3>1. 기본정보</h3>
      <table class="report-table"><tbody>
        <tr><th>법인명</th><td>${escapeHtml(input.company)}</td></tr>
        <tr><th>기업 구분</th><td>${escapeHtml(input.companySize || '미입력')}</td></tr>
        <tr><th>총매출</th><td class="amount">${formatNum(input.total_sales)}원</td></tr>
        <tr><th>영업이익</th><td class="amount">${formatNum(input.operating_income)}원</td></tr>
        <tr><th>법인세 상당액</th><td class="amount">${formatNum(input.corporate_tax)}원</td></tr>
      </tbody></table>
    </section>

    <section class="report-section"><h3>2. 판정 요건 및 계산 결과</h3>
      <table class="report-table"><tbody>
        <tr><th>특수관계자 매출 합계</th><td class="amount">${formatNum(relatedTotal)}원</td></tr>
        <tr><th>특수관계자 매출 비율</th><td class="amount">${(relatedRatio * 100).toFixed(1)}%</td></tr>
        <tr><th>정상 거래 비율</th><td class="amount">${(normalRatio * 100).toFixed(1)}%</td></tr>
        ${input.isAdmin ? `<tr><th>과세제외매출(공통)¹</th><td class="amount">${formatNum(r.excluded_sales_common)}원</td></tr>
        <tr><th>과세제외매출(계산 범위)²</th><td class="amount">${formatNum(r.excluded_sales_min)}원 ~ ${formatNum(r.excluded_sales_max)}원</td></tr>
        <tr><th>제외 후 특수관계 매출 비율</th><td class="amount">${(r.adjusted_related_ratio_min * 100).toFixed(1)}% ~ ${(r.adjusted_related_ratio_max * 100).toFixed(1)}%</td></tr>` : ''}
        <tr><th>증여의제 금액</th><td class="amount">${formatNum(r.deemed_gift_total)}원</td></tr>
        <tr><th>산출 증여세</th><td class="amount"><strong>${formatNum(r.gift_tax_total)}원</strong></td></tr>
      </tbody></table>
      ${input.isAdmin ? '<div class="hint">¹ 제10항 기준으로 공통 제외된 매출입니다. ² 서버의 민감한 지분 계산을 집계한 범위이며 원본 비율은 표시하지 않습니다.</div>' : ''}
    </section>

    <section class="report-section"><h3>3. 특수관계자 세부매출</h3>
      <table class="report-table"><thead><tr><th>거래처명</th><th>매출액</th></tr></thead><tbody>${relatedRows || emptyRow}</tbody></table>
    </section>

    <section class="report-section"><h3>4. 세무조정내역</h3>
      <table class="report-table"><thead><tr><th>조정 항목</th><th>금액</th></tr></thead><tbody>${taxRows || emptyRow}${taxTotalRow}</tbody></table>
      <div class="hint">세후영업이익 = 영업이익 ± 세무조정금액 − 법인세 상당액</div>
    </section>

    ${adminLogic}
  `
}

function escapeHtml(s){ return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') }
