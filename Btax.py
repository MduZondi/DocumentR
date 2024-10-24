import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore, auth, storage
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go
from fpdf import FPDF
import json
import uuid
from PIL import Image
import tempfile
import os
import io

# Initialize Firebase Admin
@st.cache_resource
def init_firebase_admin():
    if not firebase_admin._apps:
        try:
            firebase_creds = json.loads(st.secrets["firebase_credentials"])
            cred = credentials.Certificate(firebase_creds)
            firebase_admin.initialize_app(cred, {
                'storageBucket': f"{st.secrets['firebase_config']['project_id']}.appspot.com"
            })
        except Exception as e:
            st.error(f"Error initializing Firebase: {str(e)}")
    return firestore.client()

def calculate_business_tax(taxable_income):
    """Calculate business tax based on current SARS rates"""
    # Current company tax rate is 27% (as of 2024)
    tax_rate = 0.27
    tax_amount = taxable_income * tax_rate
    return tax_amount, tax_rate

def calculate_small_business_tax(taxable_income):
    """Calculate tax for small business corporations"""
    tax_brackets = [
        (0, 91250, 0, 0),
        (91251, 365000, 0.07, 0),
        (365001, 550000, 0.21, 19162.50),
        (550001, float('inf'), 0.28, 58037.50)
    ]
    
    for min_income, max_income, rate, base_tax in tax_brackets:
        if min_income <= taxable_income <= max_income:
            tax = base_tax + (taxable_income - min_income + 1) * rate
            return tax, rate
    return 0, 0

def upload_document_to_firebase(business_id, file):
    """Upload document to Firebase Storage"""
    if file:
        try:
            bucket = storage.bucket()
            file_extension = os.path.splitext(file.name)[1]
            blob_name = f"business_documents/{business_id}/{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())}{file_extension}"
            blob = bucket.blob(blob_name)
            
            blob.upload_from_string(
                file.getvalue(),
                content_type=file.type
            )
            
            blob.make_public()
            return blob.public_url
        except Exception as e:
            st.error(f"Error uploading document: {str(e)}")
            return None
    return None

def generate_tax_report(business_data, expenses, tax_summary, filename='Business_Tax_Report.pdf'):
    pdf = FPDF()
    
    # Cover Page
    pdf.add_page()
    pdf.set_font("Arial", 'B', size=24)
    pdf.cell(200, 40, txt="Business Tax Report & Analysis", ln=True, align='C')
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=f"Generated on: {datetime.now().strftime('%Y-%m-%d')}", ln=True, align='C')
    pdf.cell(200, 10, txt=f"Business Name: {business_data.get('business_name', '')}", ln=True, align='C')
    
    # Financial Summary
    pdf.add_page()
    pdf.set_font("Arial", 'B', size=16)
    pdf.cell(200, 20, txt="Financial Summary", ln=True)
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=f"Gross Revenue: R{business_data.get('gross_revenue', 0):,.2f}", ln=True)
    pdf.cell(200, 10, txt=f"Total Expenses: R{tax_summary.get('total_expenses', 0):,.2f}", ln=True)
    pdf.cell(200, 10, txt=f"Taxable Income: R{tax_summary.get('taxable_income', 0):,.2f}", ln=True)
    pdf.cell(200, 10, txt=f"Estimated Tax: R{tax_summary.get('estimated_tax', 0):,.2f}", ln=True)
    
    # Deductions Summary
    pdf.add_page()
    pdf.set_font("Arial", 'B', size=16)
    pdf.cell(200, 20, txt="Deductions Summary", ln=True)
    pdf.set_font("Arial", size=12)
    for category, amount in tax_summary.get('deductions', {}).items():
        pdf.cell(200, 10, txt=f"{category}: R{amount:,.2f}", ln=True)
    
    return pdf

def main():
    db = init_firebase_admin()
    
    # Authentication
    if 'user' not in st.session_state:
        st.title("Business Tax Management System - Login")
        
        tab1, tab2 = st.tabs(["Login", "Sign Up"])
        
        with tab1:
            email = st.text_input("Email", key="login_email")
            password = st.text_input("Password", type="password", key="login_password")
            
            if st.button("Login"):
                try:
                    user = auth.get_user_by_email(email)
                    st.session_state['user'] = {'localId': user.uid, 'email': email}
                    st.success("Logged in successfully!")
                    st.rerun()
                except Exception as e:
                    st.error("Login failed")
        
        with tab2:
            email = st.text_input("Email", key="signup_email")
            password = st.text_input("Password", type="password", key="signup_password")
            business_name = st.text_input("Business Name")
            business_type = st.selectbox("Business Type", [
                "Small Business Corporation",
                "Medium to Large Corporation",
                "Sole Proprietorship",
                "Partnership"
            ])
            
            if st.button("Sign Up"):
                try:
                    user = auth.create_user(email=email, password=password)
                    # Create business profile
                    db.collection('businesses').document(user.uid).set({
                        'business_name': business_name,
                        'business_type': business_type,
                        'created_at': datetime.now()
                    })
                    st.success("Account created! Please login.")
                except Exception as e:
                    st.error(f"Sign up failed: {str(e)}")
        return

    # Main app UI
    st.title("Business Tax Management System")
    
    if st.sidebar.button("Logout"):
        del st.session_state['user']
        st.rerun()

    business_id = st.session_state.user['localId']
    business_ref = db.collection('businesses').document(business_id)
    business_data = business_ref.get().to_dict() or {}

    # Navigation
    page = st.sidebar.radio("Navigate to", [
        "Dashboard",
        "Income & Revenue",
        "Expenses & Deductions",
        "Asset Management",
        "Tax Calculator",
        "Reports"
    ])

    if page == "Dashboard":
        st.header("Business Dashboard")
        
        # Display business info
        st.subheader(f"Business: {business_data.get('business_name', 'Not Set')}")
        st.write(f"Type: {business_data.get('business_type', 'Not Set')}")
        
        # Load financial data
        expenses = list(business_ref.collection('expenses').stream())
        expenses_data = [doc.to_dict() for doc in expenses]
        
        if expenses_data:
            df = pd.DataFrame(expenses_data)
            
            # Key metrics
            col1, col2, col3 = st.columns(3)
            with col1:
                total_expenses = df['amount'].sum()
                st.metric("Total Expenses", f"R {total_expenses:,.2f}")
            with col2:
                monthly_average = df.groupby(pd.to_datetime(df['date']).dt.to_period('M'))['amount'].mean()
                st.metric("Monthly Average", f"R {monthly_average.mean():,.2f}")
            with col3:
                potential_savings = df['amount'].sum() * 0.27  # Approximate tax savings
                st.metric("Potential Tax Savings", f"R {potential_savings:,.2f}")
            
            # Charts
            st.subheader("Expense Analysis")
            fig1 = px.line(
                x=df.groupby(pd.to_datetime(df['date']).dt.to_period('M'))['amount'].sum().index.astype(str),
                y=df.groupby(pd.to_datetime(df['date']).dt.to_period('M'))['amount'].sum().values,
                title="Monthly Expenses"
            )
            st.plotly_chart(fig1)
            
            fig2 = px.pie(
                values=df.groupby('category')['amount'].sum(),
                names=df.groupby('category')['amount'].sum().index,
                title="Expenses by Category"
            )
            st.plotly_chart(fig2)

    elif page == "Income & Revenue":
        st.header("Income & Revenue Management")
        
        with st.form("revenue_form"):
            st.subheader("Revenue Details")
            gross_revenue = st.number_input("Annual Gross Revenue (R)", min_value=0.0, format="%.2f")
            other_income = st.number_input("Other Income (R)", min_value=0.0, format="%.2f")
            
            # Revenue streams
            st.subheader("Revenue Streams")
            main_products = st.number_input("Product Sales (R)", min_value=0.0, format="%.2f")
            services = st.number_input("Service Revenue (R)", min_value=0.0, format="%.2f")
            investments = st.number_input("Investment Income (R)", min_value=0.0, format="%.2f")
            
            submitted = st.form_submit_button("Save Revenue Details")
            if submitted:
                data = {
                    'gross_revenue': gross_revenue,
                    'other_income': other_income,
                    'revenue_streams': {
                        'products': main_products,
                        'services': services,
                        'investments': investments
                    },
                    'updated_at': datetime.now()
                }
                business_ref.set(data, merge=True)
                st.success("Revenue details saved successfully!")

    elif page == "Expenses & Deductions":
        st.header("Expenses & Deductions Management")
        
        # SARS business expense categories
        expense_categories = {
            "Operating Costs": [
                "Rent",
                "Utilities",
                "Insurance",
                "Office Supplies",
                "Communications"
            ],
            "Employee Costs": [
                "Salaries",
                "Wages",
                "Employee Benefits",
                "Training",
                "UIF Contributions"
            ],
            "Capital Expenses": [
                "Equipment",
                "Vehicles",
                "Buildings",
                "Renovations",
                "Software"
            ],
            "Professional Services": [
                "Legal Fees",
                "Accounting Fees",
                "Consulting Fees",
                "IT Services"
            ],
            "Marketing & Sales": [
                "Advertising",
                "Marketing",
                "Travel",
                "Entertainment"
            ],
            "Research & Development": [
                "R&D Materials",
                "R&D Equipment",
                "R&D Labor",
                "Patents"
            ]
        }
        
        with st.form("expense_form"):
            col1, col2 = st.columns(2)
            
            with col1:
                main_category = st.selectbox("Main Category", list(expense_categories.keys()))
                sub_category = st.selectbox("Sub Category", expense_categories[main_category])
                description = st.text_input("Description")
            
            with col2:
                amount = st.number_input("Amount (R)", min_value=0.0, format="%.2f")
                date = st.date_input("Date")
                is_capital_expense = st.checkbox("Is this a capital expense?")
            
            document_file = st.file_uploader("Upload Supporting Document", 
                type=["jpg", "jpeg", "png", "pdf"])
            
            submitted = st.form_submit_button("Add Expense")
            if submitted:
                document_url = upload_document_to_firebase(business_id, document_file)
                
                expense_data = {
                    "main_category": main_category,
                    "sub_category": sub_category,
                    "description": description,
                    "amount": amount,
                    "date": date.strftime('%Y-%m-%d'),
                    "is_capital_expense": is_capital_expense,
                    "document_url": document_url,
                    "timestamp": datetime.now()
                }
                
                business_ref.collection('expenses').add(expense_data)
                st.success("Expense recorded successfully!")

        # Display tax-saving tips based on expense category
        st.subheader("Tax Savings Tips")
        tips = {
            "Operating Costs": "Keep detailed records of all operating expenses. Consider prepaying certain expenses before year-end if beneficial.",
            "Employee Costs": "Employee training costs are fully deductible. Consider implementing learnership programs for additional tax benefits.",
            "Capital Expenses": "Utilize SARS wear and tear allowances. Consider Section 12J investments for tax benefits.",
            "Professional Services": "Professional fees are generally deductible if they relate to your business operations.",
            "Marketing & Sales": "Entertainment expenses must be supported by detailed records to be deductible.",
            "Research & Development": "R&D expenses may qualify for special tax incentives. Consult with a tax professional."
        }
        
        selected_category = st.selectbox("Select category for tax tips", list(tips.keys()))
        st.info(tips[selected_category])

    elif page == "Asset Management":
        st.header("Asset Management")
        
        # Asset Categories based on SARS depreciation rules
        asset_categories = {
            "Buildings": 20,  # years
            "Machinery": 5,
            "Office Equipment": 3,
            "Computers": 3,
            "Vehicles": 5,
            "Furniture": 6,
            "Software": 2
        }
        
        with st.form("asset_form"):
            col1, col2 = st.columns(2)
            
            with col1:
                asset_category = st.selectbox("Asset Category", list(asset_categories.keys()))
                asset_description = st.text_input("Asset Description")
                purchase_date = st.date_input("Purchase Date")
            
            with col2:
                purchase_cost = st.number_input("Purchase Cost (R)", min_value=0.0, format="%.2f")
                expected_life = st.number_input("Expected Life (Years)", 
                    min_value=1, value=asset_categories[asset_category])
                
            document_file = st.file_uploader("Upload Purchase Document", 
                type=["jpg", "jpeg", "png", "pdf"])
            
            submitted = st.form_submit_button("Add Asset")
            if submitted:
                document_url = upload_document_to_firebase(business_id, document_file)
                
                asset_data = {
                    "category": asset_category,
                    "description": asset_description,
                    "purchase_date": purchase_date.strftime('%Y-%m-%d'),
                    "purchase_cost": purchase_cost,
                    "expected_life": expected_life,
                    "document_url": document_url,
                    "timestamp": datetime.now()
                }
                
                business_ref.collection('assets').add(asset_data)
                st.success("Asset recorded successfully!")

        # Display Assets and Depreciation Schedule
        assets = list(business_ref.collection('assets').stream())
        if assets:
            st.subheader("Asset Register & Depreciation Schedule")
            
            asset_df = pd.DataFrame([doc.to_dict() for doc in assets])
            asset_df['purchase_date'] = pd.to_datetime(asset_df['purchase_date'])
            
            # Calculate depreciation for each asset
            current_year = datetime.now().year
            
            def calculate_depreciation(row):
                years_owned = (datetime.now() - row['purchase_date']).days / 365
                annual_depreciation = row['purchase_cost'] / row['expected_life']
                accumulated_depreciation = min(years_owned * annual_depreciation, row['purchase_cost'])
                return pd.Series({
                    'Annual Depreciation': annual_depreciation,
                    'Accumulated Depreciation': accumulated_depreciation,
                    'Current Value': max(row['purchase_cost'] - accumulated_depreciation, 0)
                })
            
            asset_df[['Annual Depreciation', 'Accumulated Depreciation', 'Current Value']] = \
                asset_df.apply(calculate_depreciation, axis=1)
            
            # Display summary
            st.dataframe(asset_df[[
                'category', 'description', 'purchase_cost', 
                'Annual Depreciation', 'Accumulated Depreciation', 'Current Value'
            ]].style.format({
                'purchase_cost': 'R{:,.2f}',
                'Annual Depreciation': 'R{:,.2f}',
                'Accumulated Depreciation': 'R{:,.2f}',
                'Current Value': 'R{:,.2f}'
            }))
            
            # Depreciation chart
            fig = px.bar(
                asset_df,
                x='description',
                y=['purchase_cost', 'Current Value'],
                title="Asset Values and Depreciation",
                barmode='group'
            )
            st.plotly_chart(fig)

    elif page == "Tax Calculator":
        st.header("Business Tax Calculator")
        
        # Load business data
        business_data = business_ref.get().to_dict() or {}
        expenses = list(business_ref.collection('expenses').stream())
        assets = list(business_ref.collection('assets').stream())
        
        # Calculate total revenue
        gross_revenue = business_data.get('gross_revenue', 0)
        other_income = business_data.get('other_income', 0)
        total_revenue = gross_revenue + other_income
        
        # Calculate total expenses
        expense_data = [doc.to_dict() for doc in expenses]
        total_expenses = sum(expense['amount'] for expense in expense_data)
        
        # Calculate depreciation
        asset_data = [doc.to_dict() for doc in assets]
        total_depreciation = sum(
            doc['purchase_cost'] / doc['expected_life']
            for doc in asset_data
        )
        
        # Display calculations
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Income")
            st.metric("Gross Revenue", f"R {gross_revenue:,.2f}")
            st.metric("Other Income", f"R {other_income:,.2f}")
            st.metric("Total Revenue", f"R {total_revenue:,.2f}")
        
        with col2:
            st.subheader("Deductions")
            st.metric("Total Expenses", f"R {total_expenses:,.2f}")
            st.metric("Depreciation", f"R {total_depreciation:,.2f}")
            total_deductions = total_expenses + total_depreciation
            st.metric("Total Deductions", f"R {total_deductions:,.2f}")
        
        # Calculate taxable income
        taxable_income = max(0, total_revenue - total_deductions)
        st.subheader("Tax Calculation")
        
        # Different tax calculations based on business type
        if business_data.get('business_type') == "Small Business Corporation":
            tax_amount, tax_rate = calculate_small_business_tax(taxable_income)
            st.write("Using Small Business Corporation tax rates")
        else:
            tax_amount, tax_rate = calculate_business_tax(taxable_income)
            st.write("Using standard corporate tax rates")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Taxable Income", f"R {taxable_income:,.2f}")
        with col2:
            st.metric("Tax Rate", f"{tax_rate*100:.1f}%")
        with col3:
            st.metric("Estimated Tax", f"R {tax_amount:,.2f}")
        
        # Tax optimization tips
        st.subheader("Tax Optimization Opportunities")
        
        # Check for potential deductions
        if total_depreciation == 0:
            st.warning("💡 No depreciation recorded. Consider recording your business assets to claim depreciation.")
        
        if not any(e['main_category'] == 'Research & Development' for e in expense_data):
            st.info("💡 Consider R&D investments - they may qualify for special tax incentives.")
        
        if total_revenue > 1000000 and business_data.get('business_type') != "Small Business Corporation":
            st.info("💡 Consider restructuring as a Small Business Corporation if you qualify - it may reduce your tax burden.")

    elif page == "Reports":
        st.header("Reports and Analysis")
        
        report_type = st.selectbox("Select Report Type", [
            "Tax Summary",
            "Expense Analysis",
            "Deduction Optimization",
            "Asset Depreciation",
            "Provisional Tax Planning"
        ])
        
        if report_type == "Tax Summary":
            st.subheader("Tax Summary Report")
            
            # Gather all relevant data
            business_data = business_ref.get().to_dict() or {}
            expenses = list(business_ref.collection('expenses').stream())
            expenses_data = [doc.to_dict() for doc in expenses]
            assets = list(business_ref.collection('assets').stream())
            assets_data = [doc.to_dict() for doc in assets]
            
            # Calculate key metrics
            total_revenue = business_data.get('gross_revenue', 0) + business_data.get('other_income', 0)
            total_expenses = sum(e['amount'] for e in expenses_data)
            total_depreciation = sum(
                a['purchase_cost'] / a['expected_life']
                for a in assets_data
            )
            
            # Categorize deductions
            deductions = {}
            for expense in expenses_data:
                category = expense['main_category']
                if category not in deductions:
                    deductions[category] = 0
                deductions[category] += expense['amount']
            
            # Calculate tax
            taxable_income = max(0, total_revenue - total_expenses - total_depreciation)
            if business_data.get('business_type') == "Small Business Corporation":
                estimated_tax, tax_rate = calculate_small_business_tax(taxable_income)
            else:
                estimated_tax, tax_rate = calculate_business_tax(taxable_income)
            
            # Create summary dictionary
            tax_summary = {
                'total_revenue': total_revenue,
                'total_expenses': total_expenses,
                'total_depreciation': total_depreciation,
                'taxable_income': taxable_income,
                'estimated_tax': estimated_tax,
                'tax_rate': tax_rate,
                'deductions': deductions
            }
            
            # Display summary
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Total Revenue", f"R {total_revenue:,.2f}")
                st.metric("Total Expenses", f"R {total_expenses:,.2f}")
                st.metric("Total Depreciation", f"R {total_depreciation:,.2f}")
            
            with col2:
                st.metric("Taxable Income", f"R {taxable_income:,.2f}")
                st.metric("Tax Rate", f"{tax_rate*100:.1f}%")
                st.metric("Estimated Tax", f"R {estimated_tax:,.2f}")
            
            # Deductions breakdown
            st.subheader("Deductions Breakdown")
            fig = px.pie(
                values=list(deductions.values()),
                names=list(deductions.keys()),
                title="Deductions by Category"
            )
            st.plotly_chart(fig)
            
            # Generate PDF Report
            if st.button("Generate PDF Report"):
                pdf = generate_tax_report(business_data, expenses_data, tax_summary)
                
                # Save to temporary file
                with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
                    pdf.output(tmp.name)
                    
                    # Offer download
                    with open(tmp.name, "rb") as pdf_file:
                        st.download_button(
                            "Download Tax Summary Report",
                            pdf_file,
                            file_name=f"Business_Tax_Summary_{datetime.now().strftime('%Y%m%d')}.pdf",
                            mime="application/pdf"
                        )
                    
                    os.unlink(tmp.name)

if __name__ == "__main__":
    main()